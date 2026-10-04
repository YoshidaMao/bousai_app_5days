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

    def test_register_and_display_shelter_details(self):
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True

        response = self.client.post('/shelter_register', data={
            'name': '青森市民体育館',
            'address': '青森市合浦一丁目',
            'status': '開設中',
            'capacity': '100',
            'evacuees': '40',
            'pets_allowed': 'yes',
            'barrier_free': 'no'
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(app_module.shelters[-1]['address'], '青森市合浦一丁目')
        self.assertEqual(app_module.shelters[-1]['status'], '開設中')
        self.assertEqual(app_module.shelters[-1]['capacity'], 100)
        self.assertEqual(app_module.shelters[-1]['evacuees'], 40)
        self.assertEqual(app_module.shelters[-1]['pets_allowed'], 'yes')
        self.assertEqual(app_module.shelters[-1]['barrier_free'], 'no')

        results = self.client.get('/all_shelters')
        self.assertEqual(results.status_code, 200)
        self.assertIn('青森市民体育館', results.get_data(as_text=True))
        self.assertIn('青森市合浦一丁目', results.get_data(as_text=True))
        self.assertIn('開設中', results.get_data(as_text=True))
        self.assertIn('空きあり（あと60人）', results.get_data(as_text=True))
        self.assertIn('ペット可', results.get_data(as_text=True))
        self.assertIn('バリアフリー非対応', results.get_data(as_text=True))
        self.assertIn('facility-label--yes', results.get_data(as_text=True))
        self.assertIn('facility-label--no', results.get_data(as_text=True))
        self.assertIn('>未登録<', results.get_data(as_text=True))

    def test_unknown_facility_support_is_not_reported_as_unavailable(self):
        app_module.shelters = [{'id': 1, 'name': '未確認施設'}]

        response = self.client.get('/all_shelters')
        body = response.get_data(as_text=True)

        self.assertIn('ペット未確認', body)
        self.assertIn('バリアフリー未確認', body)
        self.assertIn('facility-label--unknown', body)

    def test_reject_invalid_facility_support_value(self):
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True

        response = self.client.post('/shelter_register', data={
            'name': '不正な設備情報',
            'pets_allowed': 'sometimes'
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(app_module.shelters, self.original_shelters)

    def test_occupancy_status_colors(self):
        app_module.shelters = [
            {'id': 1, 'name': '空きあり', 'capacity': 10, 'evacuees': 3},
            {'id': 2, 'name': '満員', 'capacity': 10, 'evacuees': 10},
            {'id': 3, 'name': '定員超過', 'capacity': 10, 'evacuees': 12},
            {'id': 4, 'name': '未登録', 'capacity': None, 'evacuees': None},
        ]

        response = self.client.get('/all_shelters')
        body = response.get_data(as_text=True)

        self.assertIn('occupancy-status--available">空きあり', body)
        self.assertIn('occupancy-status--full">満員', body)
        self.assertIn('定員超過（2人）', body)
        self.assertIn('occupancy-status--unknown">不明', body)

    def test_reject_invalid_occupancy_numbers(self):
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True

        response = self.client.post('/shelter_register', data={
            'name': '不正値の避難所',
            'capacity': '10人',
            'evacuees': '3'
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(app_module.shelters, self.original_shelters)

    def test_reject_invalid_shelter_status(self):
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True

        response = self.client.post('/shelter_register', data={
            'name': '不正な状況の避難所',
            'status': '不正な状況'
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(app_module.shelters, self.original_shelters)

    def test_search_no_results_shows_explanation_and_retry_button(self):
        response = self.client.get('/search_results?district=該当なし')
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('条件に合う避難所が見つかりませんでした', body)
        self.assertIn('地区「該当なし」', body)
        self.assertIn('条件を変えて再検索', body)
        self.assertIn('/shelter_search?district=%E8%A9%B2%E5%BD%93%E3%81%AA%E3%81%97', body)

    def test_retry_search_form_preserves_and_allows_editing_district(self):
        response = self.client.get('/shelter_search?district=中央地区')
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('name="district"', body)
        self.assertIn('value="中央地区"', body)
        self.assertIn('action="/search_results"', body)

    def test_search_by_district_returns_matching_shelters(self):
        app_module.shelters = [
            {'id': 1, 'name': '中央避難所', 'district': '中央地区'},
            {'id': 2, 'name': '東部避難所', 'district': '東部地区'}
        ]

        response = self.client.get('/search_results?district=中央地区')
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('中央避難所', body)
        self.assertNotIn('東部避難所', body)


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
