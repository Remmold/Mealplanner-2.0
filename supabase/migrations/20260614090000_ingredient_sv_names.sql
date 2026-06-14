-- Swedish ingredient display names moved out of the build-time frontend file
-- (frontend/src/i18n/ingredient-names.sv.ts) into the DB, so they're editable
-- at runtime via the admin back-office instead of needing a rebuild.
-- fdc_id -> Swedish name; the frontend loads the map from GET /ingredients/sv-names.
create table if not exists hearth.ingredient_sv_names (
    fdc_id   integer primary key,
    name_sv  text not null
);

alter table hearth.ingredient_sv_names enable row level security;

drop policy if exists ingredient_sv_read on hearth.ingredient_sv_names;
create policy ingredient_sv_read on hearth.ingredient_sv_names
    for select to authenticated using (true);

grant select                         on hearth.ingredient_sv_names to authenticated;
grant select, insert, update, delete on hearth.ingredient_sv_names to service_role;
