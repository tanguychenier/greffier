"""The services a person can connect, and the tools each power stands for.

Every tool name below was read from the server itself on 2026-09-16,
through the protocol's own listing, not from a page. What is left out is
left out on purpose, nothing that deletes, archives, sends a message or
shares a file: the person sends and deletes herself.
"""

from __future__ import annotations

from greffier.domain.accounts import Manner, Power, Server, Service

TRELLO = Service(
    key="trello",
    name="Trello",
    manner=Manner.TOKEN,
    fields=("cle", "jeton"),
    key_page="https://trello.com/power-ups/admin",
    server=Server(
        command="npx",
        args=("-y", "@delorenj/mcp-server-trello"),
        env={"TRELLO_API_KEY": "{cle}", "TRELLO_TOKEN": "{jeton}"},
    ),
    powers=(
        Power("lire", True, (
            "list_boards", "list_workspaces", "list_boards_in_workspace",
            "set_active_board", "set_active_workspace", "get_active_board_info",
            "get_lists", "get_cards_by_list_id", "get_my_cards", "get_card",
            "get_card_comments", "get_recent_activity", "get_checklist_items",
            "get_checklist_by_name", "get_acceptance_criteria",
            "find_checklist_items_by_description", "get_board_members",
            "get_board_labels", "get_card_history",
        )),
        Power("ecrire", False, (
            "add_card_to_list", "add_cards_to_list", "update_card_details", "move_card",
            "add_comment", "create_checklist", "add_checklist_item",
            "update_checklist_item", "add_list_to_board", "assign_member_to_card",
            "create_label",
        )),
    ),
)

GITLAB = Service(
    key="gitlab",
    name="GitLab",
    manner=Manner.TOKEN,
    fields=("adresse", "jeton"),
    key_page="{adresse}/-/user_settings/personal_access_tokens",
    server=Server(
        command="npx",
        args=("-y", "@zereight/mcp-gitlab"),
        env={"GITLAB_API_URL": "{adresse}/api/v4",
             "GITLAB_PERSONAL_ACCESS_TOKEN": "{jeton}"},
    ),
    powers=(
        Power("lire", True, (
            "list_projects", "get_project", "search_repositories", "list_issues",
            "my_issues", "get_issue", "list_issue_discussions", "list_issue_links",
            "list_merge_requests", "get_merge_request", "get_merge_request_notes",
            "list_labels", "get_label", "list_project_members", "get_project_events",
            "list_group_projects", "list_group_merge_requests",
        )),
        Power("ecrire", False, (
            "create_issue", "update_issue", "create_issue_note", "update_issue_note",
            "create_note", "create_merge_request_note", "create_label",
        )),
    ),
)

JIRA = Service(
    key="jira",
    name="Jira",
    manner=Manner.TOKEN,
    fields=("adresse", "courriel", "jeton"),
    key_page="https://id.atlassian.com/manage-profile/security/api-tokens",
    server=Server(
        command="uvx",
        args=("mcp-atlassian",),
        env={"JIRA_URL": "{adresse}", "JIRA_USERNAME": "{courriel}",
             "JIRA_API_TOKEN": "{jeton}"},
    ),
    powers=(
        Power("lire", True, (
            "jira_search", "jira_get_issue", "jira_get_project_issues",
            "jira_get_transitions", "jira_get_agile_boards", "jira_get_board_issues",
            "jira_get_sprints_from_board", "jira_get_sprint_issues",
            "jira_get_project_issue_types", "jira_search_fields", "jira_get_user_profile",
            "jira_search_assignable_users", "jira_get_link_types",
        )),
        Power("ecrire", False, (
            "jira_create_issue", "jira_update_issue", "jira_add_comment",
            "jira_edit_comment", "jira_transition_issue", "jira_assign_issue",
            "jira_link_to_epic", "jira_create_issue_link", "jira_add_issues_to_sprint",
        )),
    ),
)

MICROSOFT = Service(
    key="microsoft",
    name="Microsoft 365 (Outlook, agenda, tâches)",
    manner=Manner.DEVICE,
    server=Server(
        command="npx",
        args=("-y", "@softeria/ms-365-mcp-server"),
    ),
    powers=(
        Power("lire_agenda", True, (
            "list-calendars", "list-calendar-events", "get-calendar-event",
            "get-calendar-view", "get-specific-calendar-view",
            "list-specific-calendar-events", "get-specific-calendar-event",
            "list-calendar-event-instances", "get-current-user", "get-my-profile",
            "list-supported-time-zones",
        )),
        Power("ecrire_agenda", False, (
            "create-calendar-event", "update-calendar-event",
            "create-specific-calendar-event", "update-specific-calendar-event",
            "accept-calendar-event", "tentatively-accept-calendar-event",
            "decline-calendar-event",
        )),
        Power("lire_courriel", True, (
            "list-mail-folders", "list-mail-child-folders", "list-mail-messages",
            "list-mail-folder-messages", "get-mail-message", "list-mail-attachments",
            "get-mail-tips",
        )),
        Power("preparer_courriel", False, (
            "create-draft-email", "create-reply-draft", "create-reply-all-draft",
            "create-forward-draft",
        )),
        Power("taches", False, (
            "list-todo-task-lists", "list-todo-tasks", "get-todo-task",
            "create-todo-task", "update-todo-task", "list-planner-tasks",
            "get-planner-task", "create-planner-task", "update-planner-task",
        )),
    ),
)

GOOGLE = Service(
    key="google",
    name="Google (agenda, Gmail)",
    manner=Manner.APPLICATION,
    server=Server(command="npx", args=("-y", "@cocal/google-calendar-mcp")),
    powers=(
        Power("lire_agenda", True, ("list-calendars", "list-events", "get-event", "search-events")),
        Power("ecrire_agenda", False, ("create-event", "update-event")),
    ),
)

CATALOGUE: list[Service] = [TRELLO, GITLAB, JIRA, MICROSOFT, GOOGLE]


def service(key: str) -> Service | None:
    return next((s for s in CATALOGUE if s.key == key), None)
