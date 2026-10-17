-- Одноразовая подготовка DEV администратором PostgreSQL, не часть deploy workflow.
-- Нет REASSIGN OWNED / ALTER ROLE / изменений владельцев БД или схем.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '30s';

DO $$
DECLARE
    previous_owner text;
BEGIN
    IF current_database() <> 'procollab_db_dev' THEN
        RAISE EXCEPTION 'Only procollab_db_dev is allowed';
    END IF;
    SELECT pg_get_userbyid(relowner) INTO previous_owner
    FROM pg_class WHERE oid = 'public.users_university'::regclass;
    IF previous_owner NOT IN ('procollab_api_dev', 'procollab_api') THEN
        RAISE EXCEPTION 'Unexpected users_university owner';
    END IF;
    IF previous_owner = 'procollab_api_dev' THEN
        ALTER TABLE ONLY public.users_university OWNER TO procollab_api;
    END IF;
    IF (SELECT pg_get_userbyid(relowner) FROM pg_class
        WHERE oid = 'public.users_university_id_seq'::regclass) <> 'procollab_api' THEN
        RAISE EXCEPTION 'University sequence owner did not follow table owner';
    END IF;
END $$;

-- Сохраняем права runtime: до переноса он имел их как владелец этой таблицы.
GRANT ALL PRIVILEGES ON TABLE public.users_university TO procollab_api_dev;
GRANT ALL PRIVILEGES ON SEQUENCE public.users_university_id_seq TO procollab_api_dev;
COMMIT;
