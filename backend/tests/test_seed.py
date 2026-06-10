from app.store import store


def test_seed_demo_populates_prototype_rows(client, seeded):
    tasks = client.get("/api/tasks").json()
    assert len(tasks) == 10
    today = [t for t in tasks if t["group"] == "Today"]
    assert len(today) == 5  # the Home dashboard's five
    labels = {t["label"] for t in today}
    assert "Pay rent" in labels and "Book dentist follow-up" in labels

    dentist = next(t for t in tasks if t["label"] == "Book dentist follow-up")
    assert dentist["due"] == "Overdue" and dentist["late"] is True
    rent = next(t for t in tasks if t["label"] == "Pay rent")
    assert rent["done"] is True and rent["due"].startswith("Done")

    memories = client.get("/api/memory").json()
    assert len(memories) == 4
    assert memories[0]["when"] == "2 days ago"


def test_seed_demo_is_idempotent(seeded):
    assert store.seed_demo() is False
    assert len(store.list_tasks()) == 10
