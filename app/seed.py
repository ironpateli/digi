import argparse
from datetime import date, datetime, timezone
from app.db import Base, SessionLocal, engine
from app.models import ActionHistory, ActionItem, Decision, Meeting, Transcript, User


def seed(if_empty: bool = False):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if if_empty and db.query(Meeting).count(): return
        if db.query(Meeting).count(): return
        users = [User(name="Asha Patel", email="asha@example.com"), User(name="Rahul Mehta", email="rahul@example.com"), User(name="Priya Shah", email="priya@example.com")]
        db.add_all(users)
        launch = Meeting(title="Product Launch Planning", type="meeting", status="completed", scheduled_at=datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc), agenda="Confirm launch timeline and ownership.", manual_notes="Marketing, product, and support discussed launch readiness.", approved_summary="The team confirmed a 15 November launch target. Marketing will prepare campaign assets, while support will complete the customer FAQ.")
        db.add(launch); db.flush()
        db.add(Transcript(meeting_id=launch.id, content="Asha: Launch is on 15 November. Rahul will prepare the checklist by 10 November. Priya will complete the support FAQ. We need final approval next week."))
        db.add(Decision(meeting_id=launch.id, title="Launch date confirmed", description="Target launch date is 15 November.", rationale="Campaign planning and release readiness align."))
        checklist = ActionItem(meeting_id=launch.id, title="Prepare launch checklist", owner_name="Rahul Mehta", due_date=date(2026, 11, 10), status="in_progress", priority="high", created_by_ai=True)
        faq = ActionItem(meeting_id=launch.id, title="Publish support FAQ", owner_name="Priya Shah", due_date=date(2026, 11, 12), status="open", priority="medium", created_by_ai=True)
        db.add_all([checklist, faq]); db.flush()
        db.add_all([ActionHistory(action_item_id=checklist.id, event_type="approved_from_ai", detail="Created from reviewed launch recap"), ActionHistory(action_item_id=faq.id, event_type="approved_from_ai", detail="Created from reviewed launch recap")])
        handover = Meeting(title="Customer Onboarding Handover", type="handover", status="completed", scheduled_at=datetime(2026, 10, 28, 9, 30, tzinfo=timezone.utc), agenda="Transfer onboarding context to Priya.", approved_summary="Priya takes over onboarding coordination. The launch checklist remains active and needs weekly status updates.")
        db.add(handover); db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--if-empty", action="store_true")
    seed(parser.parse_args().if_empty)
