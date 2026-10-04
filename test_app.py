import json
import os
import tempfile
import unittest

import app as app_module


class ShelterRegisterTest(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.original_data_file = app_module.DATA_FILE
        self.original_shelters = list(app_module.shelters)

        fd, temp_path = tempfile.mkstemp(prefix='shelters_', suffix='.json')
        os.close(fd)
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(self.original_shelters, f, ensure_ascii=False)

        self.temp_path = temp_path
        app_module.DATA_FILE = temp_path
        app_module.shelters = list(self.original_shelters)

    def tearDown(self):
        app_module.DATA_FILE = self.original_data_file
        app_module.shelters = list(self.original_shelters)
        if os.path.exists(self.temp_path):
            os.remove(self.temp_path)

    def test_register_shelter_success(self):
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['username'] = 'admin'

        response = self.client.post('/shelter_register', data={'name': '新しい避難所'})

        self.assertEqual(response.status_code, 200)
        self.assertIn('登録しました', response.get_data(as_text=True))
        self.assertEqual(app_module.shelters[-1]['name'], '新しい避難所')


class ParseAreaWarningsTest(unittest.TestCase):
    def test_resolved_warning_is_not_reported_as_active(self):
        warning_data = [
            {
                'reportDatetime': '2026-10-02T10:00:00+09:00',
                'warning': {
                    'class20Items': [{
                        'areaCode': app_module.AREA_CODE,
                        'kinds': [{'code': '15', 'status': '発表'}]
                    }]
                }
            },
            {
                'reportDatetime': '2026-10-03T10:00:00+09:00',
                'warning': {
                    'class20Items': [{
                        'areaCode': app_module.AREA_CODE,
                        'kinds': [{'code': '15', 'status': '解除'}]
                    }]
                }
            }
        ]

        warnings, report_time = app_module.parse_area_warnings(warning_data)

        self.assertEqual(warnings, [])
        self.assertEqual(report_time, '2026-10-03T10:00:00+09:00')

    def test_no_warning_report_clears_older_active_warnings(self):
        warning_data = [
            {
                'reportDatetime': '2026-10-02T10:00:00+09:00',
                'warning': {
                    'class20Items': [{
                        'areaCode': app_module.AREA_CODE,
                        'kinds': [{'code': '14', 'status': '継続'}]
                    }]
                }
            },
            {
                'reportDatetime': '2026-10-03T10:00:00+09:00',
                'warning': {
                    'class20Items': [{
                        'areaCode': app_module.AREA_CODE,
                        'kinds': [{'status': '発表警報・注意報はなし'}]
                    }]
                }
            }
        ]

        warnings, _ = app_module.parse_area_warnings(warning_data)

        self.assertEqual(warnings, [])


if __name__ == '__main__':
    unittest.main()
