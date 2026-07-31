#!/usr/bin/env bash
set -Eeuo pipefail
# Roadmap: DEV-075

readonly DEPLOY_DIR="/root/api-react-dev"
readonly FORBIDDEN_DIR="/root/api"
readonly EXPECTED_REPOSITORY="PROCOLLAB-github/api"
readonly EXPECTED_COMPOSE_PROJECT="api-react"
readonly CELERY_SERVICE="celerys"
readonly HEALTH_URL="https://api-react-dev.procollab.ru/programs/?limit=1"
readonly LOCK_FILE="${DEPLOY_DIR}/.react-dev-deploy.lock"
readonly LOCK_TIMEOUT_SECONDS=10
readonly SERVICE_WAIT_ATTEMPTS=30
readonly SERVICE_WAIT_DELAY_SECONDS=2
readonly HEALTH_ATTEMPTS=8
readonly HEALTH_RETRY_DELAY_SECONDS=5

DEPLOY_SHA="${1:-}"
GITHUB_ACTIONS_RUN_ID="${2:-}"

PREVIOUS_SHA=""
PREVIOUS_WEB_CONTAINER_ID=""
PREVIOUS_CELERY_CONTAINER_ID=""
PREVIOUS_WEB_IMAGE_ID=""
PREVIOUS_CELERY_IMAGE_ID=""
PREVIOUS_WEB_IMAGE_REF=""
PREVIOUS_CELERY_IMAGE_REF=""
HEALTH_JSON_IMAGE_ID=""
HEALTH_BODY_FILE=""
REPOSITORY_MOVED=false
BUILD_ATTEMPTED=false
MIGRATION_STARTED=false
MIGRATION_COMPLETED=false
CONTAINERS_MAY_HAVE_CHANGED=false
ERROR_HANDLING=false
COMPOSE_PROJECT=""
COMPOSE_CMD=()

log() {
    printf '[react-dev-deploy] %s\n' "$*"
}

fail() {
    printf '[react-dev-deploy] ERROR: %s\n' "$*" >&2
    return 1
}

cleanup_health_file() {
    if [[ -n "$HEALTH_BODY_FILE" && -f "$HEALTH_BODY_FILE" ]]; then
        rm -f -- "$HEALTH_BODY_FILE"
    fi
    HEALTH_BODY_FILE=""
}

restore_repository() {
    if [[ "$REPOSITORY_MOVED" == true && -n "$PREVIOUS_SHA" ]]; then
        log "Возврат repository к предыдущему commit."
        if ! git reset --hard "$PREVIOUS_SHA" >/dev/null; then
            return 1
        fi
        REPOSITORY_MOVED=false
    fi
}

restore_image_references() {
    local result=0

    if [[ "$BUILD_ATTEMPTED" != true ]]; then
        return 0
    fi

    if [[ -n "$PREVIOUS_WEB_IMAGE_ID" && -n "$PREVIOUS_WEB_IMAGE_REF" ]]; then
        docker image tag "$PREVIOUS_WEB_IMAGE_ID" "$PREVIOUS_WEB_IMAGE_REF" ||
            result=1
    fi
    if [[ -n "$PREVIOUS_CELERY_IMAGE_ID" && -n "$PREVIOUS_CELERY_IMAGE_REF" ]]; then
        docker image tag "$PREVIOUS_CELERY_IMAGE_ID" "$PREVIOUS_CELERY_IMAGE_REF" ||
            result=1
    fi

    return "$result"
}

compose_service_container_id() {
    local service="$1"
    local -n result_variable="$2"
    local output
    local container_ids=()

    output="$("${COMPOSE_CMD[@]}" ps --all --quiet "$service")"
    if [[ -n "$output" ]]; then
        mapfile -t container_ids <<< "$output"
    fi
    if ((${#container_ids[@]} != 1)); then
        printf '[react-dev-deploy] Service %s has %d containers; expected 1.\n' \
            "$service" "${#container_ids[@]}" >&2
        return 1
    fi

    result_variable="${container_ids[0]}"
}

wait_for_service_running() {
    local service="$1"
    local attempt
    local container_id=""
    local status=""
    local restarting=""

    for ((attempt = 1; attempt <= SERVICE_WAIT_ATTEMPTS; attempt++)); do
        if compose_service_container_id "$service" container_id; then
            status="$(docker inspect --format '{{.State.Status}}' "$container_id")"
            restarting="$(
                docker inspect --format '{{.State.Restarting}}' "$container_id"
            )"
            if [[ "$status" == "running" && "$restarting" == "false" ]]; then
                return 0
            fi
        fi
        sleep "$SERVICE_WAIT_DELAY_SECONDS"
    done

    printf '[react-dev-deploy] Service %s did not reach running state; status=%s.\n' \
        "$service" "${status:-missing}" >&2
    return 1
}

health_check() {
    local label="$1"
    local attempt
    local metadata=""
    local http_status=""
    local content_type=""

    if [[ -z "$HEALTH_JSON_IMAGE_ID" ]]; then
        printf '[react-dev-deploy] JSON parser image is not initialized.\n' >&2
        return 1
    fi

    HEALTH_BODY_FILE="$(mktemp /tmp/procollab-react-dev-health.XXXXXX)"
    for ((attempt = 1; attempt <= HEALTH_ATTEMPTS; attempt++)); do
        metadata=""
        if metadata="$(
            curl \
                --silent \
                --show-error \
                --proto '=https' \
                --max-redirs 0 \
                --connect-timeout 5 \
                --max-time 15 \
                --output "$HEALTH_BODY_FILE" \
                --write-out '%{http_code}|%{content_type}' \
                "$HEALTH_URL"
        )"; then
            http_status="${metadata%%|*}"
            content_type="${metadata#*|}"
            log "${label} health-check attempt ${attempt}: HTTP ${http_status}, content-type=${content_type:-unknown}."

            if [[ "$http_status" == "200" ]] &&
                [[ "$content_type" == *"application/json"* ]] &&
                [[ -s "$HEALTH_BODY_FILE" ]] &&
                ! grep -Eiq '^[[:space:]]*<(html|!doctype)' "$HEALTH_BODY_FILE" &&
                docker run \
                    --rm \
                    --interactive \
                    --entrypoint python \
                    "$HEALTH_JSON_IMAGE_ID" \
                    -c 'import json, sys; json.load(sys.stdin)' \
                    < "$HEALTH_BODY_FILE" \
                    >/dev/null; then
                cleanup_health_file
                return 0
            fi
        else
            log "${label} health-check attempt ${attempt}: connection failed."
        fi

        sleep "$HEALTH_RETRY_DELAY_SECONDS"
    done

    cleanup_health_file
    return 1
}

rollback_deployment() {
    local rollback_failed=0

    log "Запуск rollback React-dev code и container images."
    restore_repository || rollback_failed=1
    restore_image_references || rollback_failed=1

    if [[ "$CONTAINERS_MAY_HAVE_CHANGED" == true && "$rollback_failed" -eq 0 ]]; then
        "${COMPOSE_CMD[@]}" up \
            --detach \
            --no-deps \
            --force-recreate \
            web "$CELERY_SERVICE" ||
            rollback_failed=1

        if ((rollback_failed == 0)); then
            wait_for_service_running web || rollback_failed=1
            wait_for_service_running "$CELERY_SERVICE" || rollback_failed=1
        fi

        if ((rollback_failed == 0)); then
            HEALTH_JSON_IMAGE_ID="$PREVIOUS_WEB_IMAGE_ID"
            health_check "Rollback" || rollback_failed=1
        fi
    fi

    if ((rollback_failed != 0)); then
        printf '[react-dev-deploy] ERROR: rollback React-dev завершился ошибкой.\n' >&2
        return 1
    fi

    log "Rollback React-dev успешно завершен."
    return 0
}

handle_error() {
    local exit_code="$?"
    local line_number="${1:-unknown}"
    local rollback_status=0

    if [[ "$ERROR_HANDLING" == true ]]; then
        exit "$exit_code"
    fi

    ERROR_HANDLING=true
    trap - ERR
    set +e
    cleanup_health_file
    printf '[react-dev-deploy] ERROR: deploy failed near line %s.\n' \
        "$line_number" >&2

    if [[ "$REPOSITORY_MOVED" == true ||
        "$BUILD_ATTEMPTED" == true ||
        "$CONTAINERS_MAY_HAVE_CHANGED" == true ]]; then
        rollback_deployment
        rollback_status="$?"
    fi

    if [[ "$MIGRATION_STARTED" == true ]]; then
        printf '%s\n' \
            '[react-dev-deploy] NOTICE: примененные миграции автоматически назад не откатывались.' >&2
    fi
    if ((rollback_status != 0)); then
        printf '%s\n' \
            '[react-dev-deploy] ERROR: исходная ошибка deploy и ошибка rollback требуют ручной проверки React-dev.' >&2
    fi

    exit "$exit_code"
}

trap 'handle_error "$LINENO"' ERR

if [[ ! "$DEPLOY_SHA" =~ ^[0-9a-f]{40}$ ]]; then
    fail "DEPLOY_SHA должен состоять ровно из 40 lowercase hexadecimal символов."
fi
if [[ ! "$GITHUB_ACTIONS_RUN_ID" =~ ^[0-9]+$ ]]; then
    fail "GitHub Actions run ID должен быть числовым."
fi
if [[ "$(uname -s)" != "Linux" ]]; then
    fail "Deploy script разрешено запускать только на Linux."
fi

for required_command in git docker curl flock realpath mktemp grep; do
    if ! command -v "$required_command" >/dev/null 2>&1; then
        fail "Не найдена обязательная команда: ${required_command}."
    fi
done
if ! docker compose version >/dev/null 2>&1; then
    fail "Docker Compose plugin недоступен."
fi

if [[ ! -d "$DEPLOY_DIR" || ! -d "$DEPLOY_DIR/.git" ]]; then
    fail "React-dev repository не найден в ${DEPLOY_DIR}."
fi
actual_deploy_dir="$(realpath -e "$DEPLOY_DIR")"
if [[ "$actual_deploy_dir" != "$DEPLOY_DIR" ]]; then
    fail "React-dev repository должен иметь точный realpath ${DEPLOY_DIR}."
fi
if [[ -e "$FORBIDDEN_DIR" ]] &&
    [[ "$(realpath -e "$FORBIDDEN_DIR")" == "$actual_deploy_dir" ]]; then
    fail "Production/legacy backend path запрещен."
fi

cd -- "$actual_deploy_dir"
if [[ "$(pwd -P)" != "$DEPLOY_DIR" ]]; then
    fail "Текущий каталог не является разрешенным React-dev repository."
fi

exec 9> "$LOCK_FILE"
if ! flock --wait "$LOCK_TIMEOUT_SECONDS" 9; then
    fail "Другой React-dev deploy уже выполняется; lock не получен."
fi

origin_url="$(git remote get-url origin)"
case "$origin_url" in
    "https://github.com/${EXPECTED_REPOSITORY}" | \
        "https://github.com/${EXPECTED_REPOSITORY}.git" | \
        "git@github.com:${EXPECTED_REPOSITORY}.git" | \
        "ssh://git@github.com/${EXPECTED_REPOSITORY}" | \
        "ssh://git@github.com/${EXPECTED_REPOSITORY}.git")
        ;;
    *)
        fail "Origin не соответствует разрешенному backend repository."
        ;;
esac

PREVIOUS_SHA="$(git rev-parse HEAD)"
if ! git diff --quiet --ignore-submodules --; then
    fail "В React-dev repository есть unstaged tracked changes."
fi
if ! git diff --cached --quiet --ignore-submodules --; then
    fail "В React-dev repository есть staged tracked changes."
fi

mapfile -t current_web_containers < <(
    docker ps \
        --quiet \
        --filter "label=com.docker.compose.project=${EXPECTED_COMPOSE_PROJECT}" \
        --filter "label=com.docker.compose.service=web"
)
if ((${#current_web_containers[@]} != 1)); then
    fail "Не найден ровно один running web container проекта api-react."
fi
PREVIOUS_WEB_CONTAINER_ID="${current_web_containers[0]}"

COMPOSE_PROJECT="$(
    docker inspect \
        --format '{{ index .Config.Labels "com.docker.compose.project" }}' \
        "$PREVIOUS_WEB_CONTAINER_ID"
)"
compose_working_dir="$(
    docker inspect \
        --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' \
        "$PREVIOUS_WEB_CONTAINER_ID"
)"
compose_config_files_label="$(
    docker inspect \
        --format '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' \
        "$PREVIOUS_WEB_CONTAINER_ID"
)"

if [[ "$COMPOSE_PROJECT" != "$EXPECTED_COMPOSE_PROJECT" ]]; then
    fail "Обнаружен неожиданный Docker Compose project."
fi
if [[ -z "$compose_working_dir" || -z "$compose_config_files_label" ]]; then
    fail "У running web container отсутствуют обязательные Compose labels."
fi

compose_working_dir="$(realpath -e "$compose_working_dir")"
if [[ "$compose_working_dir" != "$DEPLOY_DIR" ]]; then
    fail "Docker Compose working_dir находится вне React-dev repository."
fi

legacy_compose_file="$(realpath -m "${DEPLOY_DIR}/docker-compose.yml")"
compose_config_files=()
IFS=',' read -r -a raw_compose_config_files <<< "$compose_config_files_label"
for raw_config_file in "${raw_compose_config_files[@]}"; do
    config_file="${raw_config_file#"${raw_config_file%%[![:space:]]*}"}"
    config_file="${config_file%"${config_file##*[![:space:]]}"}"
    if [[ -z "$config_file" ]]; then
        fail "Compose config_files label содержит пустой путь."
    fi
    if [[ "$config_file" != /* ]]; then
        config_file="${compose_working_dir}/${config_file}"
    fi
    config_file="$(realpath -e "$config_file")"
    if [[ "$config_file" != "${DEPLOY_DIR}/"* ]]; then
        fail "Compose config file находится вне React-dev repository."
    fi
    if [[ "$config_file" == "$legacy_compose_file" ]]; then
        fail "Repository legacy docker-compose.yml запрещен для React-dev deploy."
    fi
    compose_config_files+=("$config_file")
done
if ((${#compose_config_files[@]} == 0)); then
    fail "Compose config files не обнаружены."
fi

COMPOSE_CMD=(
    docker compose
    --project-name "$COMPOSE_PROJECT"
    --project-directory "$compose_working_dir"
)
for config_file in "${compose_config_files[@]}"; do
    COMPOSE_CMD+=(--file "$config_file")
done

validate_compose_services() {
    local services_output
    local service
    local expected_service
    local services=()
    local found

    services_output="$("${COMPOSE_CMD[@]}" config --services)"
    mapfile -t services <<< "$services_output"
    for expected_service in web "$CELERY_SERVICE" redis; do
        found=false
        for service in "${services[@]}"; do
            if [[ "$service" == "$expected_service" ]]; then
                found=true
                break
            fi
        done
        if [[ "$found" != true ]]; then
            printf '[react-dev-deploy] Expected Compose service is missing: %s.\n' \
                "$expected_service" >&2
            return 1
        fi
    done
}

validate_compose_services

mapfile -t current_celery_containers < <(
    docker ps \
        --quiet \
        --filter "label=com.docker.compose.project=${COMPOSE_PROJECT}" \
        --filter "label=com.docker.compose.service=${CELERY_SERVICE}"
)
if ((${#current_celery_containers[@]} != 1)); then
    fail "Не найден ровно один running celery container проекта api-react."
fi
PREVIOUS_CELERY_CONTAINER_ID="${current_celery_containers[0]}"

PREVIOUS_WEB_IMAGE_ID="$(
    docker inspect --format '{{.Image}}' "$PREVIOUS_WEB_CONTAINER_ID"
)"
PREVIOUS_CELERY_IMAGE_ID="$(
    docker inspect --format '{{.Image}}' "$PREVIOUS_CELERY_CONTAINER_ID"
)"
PREVIOUS_WEB_IMAGE_REF="$(
    docker inspect --format '{{.Config.Image}}' "$PREVIOUS_WEB_CONTAINER_ID"
)"
PREVIOUS_CELERY_IMAGE_REF="$(
    docker inspect --format '{{.Config.Image}}' "$PREVIOUS_CELERY_CONTAINER_ID"
)"
if [[ -z "$PREVIOUS_WEB_IMAGE_ID" || -z "$PREVIOUS_CELERY_IMAGE_ID" ||
    -z "$PREVIOUS_WEB_IMAGE_REF" || -z "$PREVIOUS_CELERY_IMAGE_REF" ]]; then
    fail "Не удалось сохранить image state текущих React-dev containers."
fi

git fetch origin master --prune
if ! git cat-file -e "${DEPLOY_SHA}^{commit}"; then
    fail "DEPLOY_SHA отсутствует в backend repository."
fi
origin_master_sha="$(git rev-parse --verify 'origin/master^{commit}')"
if ! git merge-base --is-ancestor "$DEPLOY_SHA" "$origin_master_sha"; then
    fail "DEPLOY_SHA не является commit из текущего origin/master."
fi
if [[ "$origin_master_sha" != "$DEPLOY_SHA" ]]; then
    log "Deploy устарел: origin/master уже содержит более новый commit."
    log "Код и containers React-dev не изменялись."
    trap - ERR
    exit 0
fi

REPOSITORY_MOVED=true
git reset --hard "$DEPLOY_SHA" >/dev/null
actual_sha="$(git rev-parse HEAD)"
if [[ "$actual_sha" != "$DEPLOY_SHA" ]]; then
    fail "Repository не перешел на DEPLOY_SHA."
fi

validate_compose_services

BUILD_ATTEMPTED=true
log "Сборка новых web и ${CELERY_SERVICE} images без остановки текущих containers."
"${COMPOSE_CMD[@]}" build web "$CELERY_SERVICE"

new_web_image_id="$(
    docker image inspect --format '{{.Id}}' "$PREVIOUS_WEB_IMAGE_REF"
)"
new_celery_image_id="$(
    docker image inspect --format '{{.Id}}' "$PREVIOUS_CELERY_IMAGE_REF"
)"
if [[ -z "$new_web_image_id" || -z "$new_celery_image_id" ]]; then
    fail "Не удалось определить новые web/celery images после build."
fi
HEALTH_JSON_IMAGE_ID="$new_web_image_id"

log "Django system check на новом web image."
"${COMPOSE_CMD[@]}" run \
    --rm \
    --no-deps \
    -T \
    web python manage.py check </dev/null

MIGRATION_STARTED=true
log "Применение миграций React-dev на новом web image."
"${COMPOSE_CMD[@]}" run \
    --rm \
    --no-deps \
    -T \
    web python manage.py migrate --noinput </dev/null
MIGRATION_COMPLETED=true

CONTAINERS_MAY_HAVE_CHANGED=true
log "Пересоздание только React-dev web и ${CELERY_SERVICE}."
"${COMPOSE_CMD[@]}" up \
    --detach \
    --no-deps \
    --force-recreate \
    web "$CELERY_SERVICE"

wait_for_service_running web
wait_for_service_running "$CELERY_SERVICE"
if ! health_check "Deploy"; then
    fail "Публичный React-dev HTTPS health-check не пройден."
fi

web_container_id=""
celery_container_id=""
compose_service_container_id web web_container_id
compose_service_container_id "$CELERY_SERVICE" celery_container_id
web_status="$(docker inspect --format '{{.State.Status}}' "$web_container_id")"
celery_status="$(docker inspect --format '{{.State.Status}}' "$celery_container_id")"

trap - ERR
log "Deploy React-dev успешно завершен."
printf '%s\n' \
    "DEPLOY_SHA=${DEPLOY_SHA}" \
    "PREVIOUS_SHA=${PREVIOUS_SHA}" \
    "GITHUB_RUN_ID=${GITHUB_ACTIONS_RUN_ID}" \
    "COMPOSE_PROJECT=${COMPOSE_PROJECT}" \
    "WEB_STATUS=${web_status}" \
    "CELERY_STATUS=${celery_status}" \
    "MIGRATION_COMPLETED=${MIGRATION_COMPLETED}" \
    "HEALTH_CHECK_COMPLETED=true"
