-- Только чтение. Выполнить до rollout; строки содержат ID, без выбора победителя.
-- Уже существующий один пользователь в нескольких командах активной программы.
WITH members AS (
    SELECT p.id AS project_id, p.leader_id AS user_id FROM projects_project p
    UNION
    SELECT c.project_id, c.user_id FROM projects_collaborator c
)
SELECT l.partner_program_id, m.user_id,
       array_agg(DISTINCT m.project_id ORDER BY m.project_id) AS project_ids
FROM members m
JOIN partner_programs_partnerprogramproject l ON l.project_id = m.project_id
JOIN partner_programs_partnerprogram p ON p.id = l.partner_program_id
WHERE p.is_competitive AND p.datetime_finished > CURRENT_TIMESTAMP
GROUP BY l.partner_program_id, m.user_id
HAVING count(DISTINCT m.project_id) > 1;

-- Pending duplicates: миграция PR B остановится при непустом результате.
SELECT project_id, user_id, array_agg(id ORDER BY id) AS invite_ids
FROM invites_invite
WHERE is_accepted IS NULL
GROUP BY project_id, user_id
HAVING count(*) > 1;

-- Ambiguous contexts: migration PR C оставит program_link NULL.
SELECT i.id AS invite_id, i.project_id,
       array_agg(l.id ORDER BY l.id) AS possible_program_link_ids
FROM invites_invite i
JOIN partner_programs_partnerprogramproject l ON l.project_id = i.project_id
GROUP BY i.id, i.project_id
HAVING count(l.id) > 1;

-- Accepted roster без регистрации в конкурсной программе.
WITH members AS (
    SELECT id AS project_id, leader_id AS user_id FROM projects_project
    UNION
    SELECT project_id, user_id FROM projects_collaborator
)
SELECT l.partner_program_id, m.project_id, m.user_id
FROM members m
JOIN partner_programs_partnerprogramproject l ON l.project_id = m.project_id
JOIN partner_programs_partnerprogram p ON p.id = l.partner_program_id
LEFT JOIN partner_programs_partnerprogramuserprofile u
  ON u.partner_program_id = l.partner_program_id AND u.user_id = m.user_id
WHERE p.is_competitive AND u.id IS NULL;
