-- 학습 프로필 동기화 테이블 (PostgreSQL)
--
-- gestureos.profile-db.enabled=true 로 쓸 때만 필요하다. 기본값은 꺼짐이고,
-- 꺼져 있으면 학습 프로필은 로컬 파일에만 저장된다.
--
-- 이 파일은 자동 실행되지 않는다. 직접 한 번 실행하면 된다:
--   psql -U sltuser -d slt -f src/main/resources/db/schema-profile.sql
--
-- LearnerProfileMapper 의 upsert 가 ON CONFLICT (member_id, profile_name) 를 쓰므로
-- 두 컬럼의 복합 PK 가 반드시 있어야 한다.

CREATE TABLE IF NOT EXISTS gestureos_learner_profile (
    member_id    bigint       NOT NULL,
    profile_name varchar(200) NOT NULL,
    model_json   text         NOT NULL,
    updated_at   timestamp    NOT NULL DEFAULT now(),
    PRIMARY KEY (member_id, profile_name)
);
