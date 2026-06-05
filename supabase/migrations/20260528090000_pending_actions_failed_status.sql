-- Allow 'failed' as a terminal status on hearth.pending_actions.
--
-- The accept_pending endpoint writes status='failed' when execute() raises,
-- which is the correct semantic (attempted, didn't succeed) and distinct
-- from 'rejected' (user declined). The original CHECK constraint omitted it.

alter table hearth.pending_actions
    drop constraint if exists pending_actions_status_check;

alter table hearth.pending_actions
    add constraint pending_actions_status_check
        check (status in ('pending', 'accepted', 'rejected', 'failed'));
