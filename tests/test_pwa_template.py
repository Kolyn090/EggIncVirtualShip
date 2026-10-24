import json
from pathlib import Path
import unittest
from build_plan_dashboard import TEMPLATE

ROOT = Path(__file__).resolve().parents[1]


class PWATemplateTests(unittest.TestCase):
    def test_offline_bundle_matches_existing_dashboard_exactly(self):
        source = (ROOT / 'pwa/dashboard-template.mjs').read_text()
        bundled = json.loads(source.split('export const dashboardTemplate = ', 1)[1].strip().removesuffix(';'))
        self.assertEqual(bundled, TEMPLATE, 'Run npm run build:pwa after dashboard template changes')


if __name__ == '__main__':
    unittest.main()
