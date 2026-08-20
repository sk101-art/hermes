import argparse
from app.inbox_view import run_inbox_view

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HERMES Intelligence Inbox")
    parser.add_argument("--unseen", action="store_true", help="Filter unseen items only")
    parser.add_argument("--starred", action="store_true", help="Filter starred items only")
    parser.add_argument("--project", type=str, default=None, help="Filter by relevant project name")
    parser.add_argument("--section", type=str, default=None, help="Filter by section name")
    parser.add_argument("--all", action="store_true", help="Include expired items")
    args = parser.parse_args()

    run_inbox_view(
        unseen_only=args.unseen,
        starred_only=args.starred,
        project_filter=args.project,
        section_filter=args.section,
        include_expired=args.all,
    )
