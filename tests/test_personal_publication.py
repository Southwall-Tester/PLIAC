"""Personal publication preserves provenance and ordinary publication checks."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from learning_agent.course_catalog import metadata
from learning_agent.course_graph import CourseGraphError, CourseGraphStore


class PersonalPublicationTests(unittest.TestCase):
    def test_personal_publication_preserves_unreviewed_content(self):
        seed = ROOT / "data/course_templates/linux_command_line/course.json"
        with tempfile.TemporaryDirectory() as temporary:
            store = CourseGraphStore(seed, Path(temporary))
            draft = store.load_graph("draft")
            with self.assertRaises(CourseGraphError):
                store.publish(draft["version"], "Synthetic publisher", "Test")
            with self.assertRaises(CourseGraphError):
                store.publish(draft["version"] + 1, "Synthetic publisher", "Test", personal_use=True)
            result = store.publish(draft["version"], "Synthetic publisher", "Test", personal_use=True)
            self.assertEqual(store.load_graph(), draft)
            self.assertEqual(store.load_graph("draft"), draft)
            self.assertFalse(store.load_graph()["authoring"]["human_review"])
            self.assertEqual(result["publication"]["publication_mode"], "personal_use")
            self.assertGreater(result["publication"]["unreviewed_item_count"], 0)
            course = metadata(store)
            self.assertTrue(course["capabilities"]["learn"])
            self.assertEqual(course["activities"][0]["href"], "/linux-lab")
            with self.assertRaises(CourseGraphError):
                store.publish(draft["version"], "Synthetic publisher", "Test")


if __name__ == "__main__":
    unittest.main()
