import json
import os
import tempfile
import unittest
from unittest.mock import patch

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

    def test_map_api_only_exposes_complete_verified_records_and_handles_bad_storage(self):
        app_module.shelters = [
            {'id': 1, 'name': '未確認', 'latitude': 40.8, 'longitude': 140.7},
            {'id': 2, 'name': '座標不正', 'latitude': 'nan', 'longitude': 140.7, 'verified': True},
            {'id': None, 'name': 'IDなし', 'latitude': 40.8, 'longitude': 140.7, 'verified': True},
            {'id': 4, 'name': '確認済み', 'district': '中央地区', 'status': '想定外', 'latitude': '40.8', 'longitude': '140.7', 'verified': True},
            None,
        ]
        response = self.client.get('/api/shelters')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['shelters'], [{
            'id': 4,
            'name': '確認済み',
            'status': '未設定',
            'latitude': 40.8,
            'longitude': 140.7,
            'district': '中央地区',
            'verified': True,
        }])

        app_module.shelters = {'unexpected': 'data'}
        malformed = self.client.get('/api/shelters')
        self.assertEqual(malformed.status_code, 200)
        self.assertEqual(malformed.json['status'], 'empty')
        self.assertEqual(malformed.json['shelters'], [])

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

    def test_verified_shelter_requires_coordinates_and_registration_persists(self):
        app_module.shelters = []
        app_module.DATA_FILE = self.temp_path
        with open(app_module.DATA_FILE, 'w', encoding='utf-8') as stream:
            json.dump([], stream)
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['username'] = 'operator'

        missing_coordinates = self.client.post('/shelter_register', data={
            'name': '未照合せず確認済みにはできない',
            'verified': 'yes',
        })
        self.assertEqual(missing_coordinates.status_code, 400)
        self.assertEqual(app_module.shelters, [])

        response = self.client.post('/shelter_register', data={
            'name': '確認済み施設',
            'district': '中央地区',
            'latitude': '40.8',
            'longitude': '140.7',
            'verified': 'yes',
        })
        self.assertIn('避難所を登録しました', response.get_data(as_text=True))
        with open(app_module.DATA_FILE, encoding='utf-8') as stream:
            persisted = json.load(stream)
        self.assertEqual(persisted[0]['district'], '中央地区')
        self.assertEqual(self.client.get('/api/shelters').json['shelters'][0]['id'], persisted[0]['id'])

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
    def test_other_municipalities_are_not_mixed_into_aomori_city(self):
        warning_data = [{
            'reportDatetime': '2026-10-03T10:00:00+09:00',
            'warning': {
                'class20Items': [
                    {'areaCode': '0220200', 'kinds': [{'code': '15', 'status': '発表'}]},
                    {'areaCode': app_module.AREA_CODE, 'kinds': [{'code': '14', 'status': '発表'}]},
                ]
            }
        }]

        warnings, _ = app_module.parse_area_warnings(warning_data)

        self.assertEqual([warning['code'] for warning in warnings], ['14'])

    def test_missing_target_municipality_is_not_reported_as_no_warnings(self):
        with self.assertRaises(ValueError):
            app_module.parse_area_warnings([{
                'reportDatetime': '2026-10-03T10:00:00+09:00',
                'warning': {'class20Items': [{
                    'areaCode': '0220200',
                    'kinds': [{'status': '発表警報・注意報はなし'}],
                }]},
            }])

    def test_warning_records_have_category_and_target_region(self):
        warnings, _ = app_module.parse_area_warnings([{
            'reportDatetime': '2026-10-03T10:00:00+09:00',
            'warning': {'class20Items': [{
                'areaCode': app_module.AREA_CODE,
                'kinds': [{'code': '15', 'status': '発表'}],
            }]},
        }])
        self.assertEqual(warnings[0]['category'], '注意報')
        self.assertEqual(warnings[0]['area_name'], '青森市')

    def test_stale_or_invalid_report_time_is_not_presented_as_current(self):
        now = app_module.datetime(2026, 10, 4, 12, tzinfo=app_module.JST)
        app_module.validate_jma_report_freshness(
            '2026-10-03T12:00:00+09:00',
            now=now,
        )
        with self.assertRaisesRegex(ValueError, '古いため'):
            app_module.validate_jma_report_freshness(
                '2026-10-01T11:59:00+09:00',
                now=now,
            )
        with self.assertRaises(ValueError):
            app_module.validate_jma_report_freshness('発表時刻不正', now=now)

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


class OfficialMunicipalInformationTest(unittest.TestCase):
    def test_parser_extracts_main_notice_not_page_number_or_contact(self):
        html = '''
        <main><article id="content"><div id="voice">
          <h1>現在発表されている災害情報</h1>
          <div class="box"><p>ページ番号1002513 更新日 2024年12月23日</p></div>
          <p>青森市から避難情報を発表しました。対象区域: 中央地区</p>
          <div id="reference"><h2>お問い合わせ</h2><p>電話: 017-000-0000</p></div>
        </div></article></main>
        '''
        result = app_module.parse_city_disaster_page(html)

        self.assertEqual(result['status'], 'active')
        self.assertIn('中央地区', result['content'])
        self.assertNotIn('ページ番号', result['content'])
        self.assertNotIn('問い合わせ', result['content'])
        self.assertNotIn('電話', result['content'])

    def test_parser_distinguishes_official_no_information_from_structure_failure(self):
        self.assertEqual(
            app_module.parse_city_disaster_page(
                '<article id="content"><p>現在、情報はありません。</p></article>'
            )['status'],
            'none',
        )
        with self.assertRaises(ValueError):
            app_module.parse_city_disaster_page('<html><body>ページ構造が変わりました</body></html>')

    def test_public_information_api_distinguishes_empty_and_fetch_error(self):
        client = app_module.app.test_client()
        empty = {
            'status': 'none',
            'content': '',
            'area_name': '青森市',
            'source_url': app_module.CITY_DISASTER_URL,
            'checked_at': '2026年10月04日 00:00',
        }
        with patch.object(app_module, 'fetch_city_disaster_information', return_value=empty), \
                patch.object(app_module, 'get_weather_warnings', return_value={'warnings': [], 'error': False}):
            response = client.get('/api/public_disaster_information')
        self.assertEqual(response.json['municipal']['status'], 'none')

        failed = {**empty, 'status': 'error'}
        with patch.object(app_module, 'fetch_city_disaster_information', return_value=failed), \
                patch.object(app_module, 'get_weather_warnings', return_value={'warnings': [], 'error': True}):
            response = client.get('/api/public_disaster_information')
        self.assertEqual(response.json['municipal']['status'], 'error')
        self.assertTrue(response.json['weather']['error'])


class DisasterAppIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.original_shelters = app_module.shelters
        self.original_instructions = app_module.instructions
        self.original_shelter_file = app_module.DATA_FILE
        self.original_instruction_file = app_module.INSTRUCTIONS_FILE
        self.temp_paths = []

    def tearDown(self):
        app_module.shelters = self.original_shelters
        app_module.instructions = self.original_instructions
        app_module.DATA_FILE = self.original_shelter_file
        app_module.INSTRUCTIONS_FILE = self.original_instruction_file
        for path in self.temp_paths:
            if os.path.exists(path):
                os.remove(path)

    def temp_json(self, prefix, value):
        fd, path = tempfile.mkstemp(prefix=prefix, suffix='.json')
        os.close(fd)
        with open(path, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
        self.temp_paths.append(path)
        return path

    def login(self):
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['username'] = 'operator'

    def test_shelter_coordinates_are_validated_and_feed_the_map_api(self):
        app_module.shelters = []
        app_module.DATA_FILE = self.temp_json('map_shelters_', [])
        self.login()
        invalid = self.client.post('/shelter_register', data={
            'name': '座標不正',
            'latitude': '91',
            'longitude': '140.7',
        })
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(app_module.shelters, [])

        missing_pair = self.client.post('/shelter_register', data={
            'name': '座標片方',
            'latitude': '40.8',
        })
        self.assertEqual(missing_pair.status_code, 400)
        self.assertEqual(app_module.shelters, [])

        saved = self.client.post('/shelter_register', data={
            'name': '管理者登録施設',
            'district': '中央地区',
            'status': '開設中',
            'latitude': '40.82',
            'longitude': '140.74',
            'verified': 'yes',
        })
        self.assertIn('避難所を登録しました', saved.get_data(as_text=True))
        api = self.client.get('/api/shelters')
        self.assertEqual(api.status_code, 200)
        self.assertEqual(api.json['status'], 'ok')
        self.assertEqual(api.json['shelters'][0]['name'], '管理者登録施設')
        self.assertEqual(api.json['shelters'][0]['status'], '開設中')
        self.assertEqual(api.json['shelters'][0]['latitude'], 40.82)
        self.assertTrue(api.json['shelters'][0]['verified'])

    def test_shelter_name_is_required_with_clear_message(self):
        app_module.shelters = []
        app_module.DATA_FILE = self.temp_json('required_name_', [])
        self.login()
        response = self.client.post('/shelter_register', data={'name': '   '})
        self.assertEqual(response.status_code, 200)
        self.assertIn('避難所名を入力してください', response.get_data(as_text=True))
        self.assertEqual(app_module.shelters, [])

    def test_map_api_skips_missing_and_invalid_coordinates_and_supports_empty_data(self):
        app_module.shelters = [
            {'id': 1, 'name': '旧データ'},
            {'id': 2, 'name': '不正座標', 'latitude': 91, 'longitude': 140},
            {'id': 3, 'name': '確認済み', 'latitude': 40.8, 'longitude': 140.7, 'status': '閉鎖', 'verified': True},
        ]
        response = self.client.get('/api/shelters')
        self.assertEqual([shelter['name'] for shelter in response.json['shelters']], ['確認済み'])
        self.assertEqual(response.json['shelters'][0]['status'], '閉鎖')

        app_module.shelters = []
        empty = self.client.get('/api/shelters')
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json['status'], 'empty')
        self.assertEqual(empty.json['shelters'], [])

    def test_legacy_shelter_records_are_marked_unverified_in_public_lists(self):
        app_module.shelters = [{'id': 1, 'name': '旧登録施設'}]
        body = self.client.get('/all_shelters').get_data(as_text=True)
        self.assertIn('施設・所在地 未確認', body)
        listed = self.client.get('/shelters')
        self.assertFalse(listed.json[0]['verified'])

    def test_resident_notice_is_the_same_persisted_record_on_home_and_board(self):
        app_module.instructions = []
        app_module.INSTRUCTIONS_FILE = self.temp_json('instructions_', [])
        self.login()

        created = self.client.post('/board', data={
            'target': '住民',
            'content': '登録された住民向けのお知らせ',
            'shelter': '',
            'urgency': 'high',
            'status': '発令中',
        })
        self.assertEqual(created.status_code, 302)
        board = self.client.get('/board').get_data(as_text=True)
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('登録された住民向けのお知らせ', board)
        self.assertIn('登録された住民向けのお知らせ', home)
        self.assertIn('緊急度: 高', home)
        self.assertIn('自治体の公式発令ではありません', home)

        instruction_id = app_module.instructions[0]['id']
        updated = self.client.post(f'/board/{instruction_id}', data={
            'target': '住民',
            'content': '更新された発信内容',
            'shelter': '',
            'urgency': 'normal',
            'status': '解除',
        })
        self.assertEqual(updated.status_code, 302)
        self.assertIn('更新された発信内容', self.client.get('/board').get_data(as_text=True))
        home_after = self.client.get('/').get_data(as_text=True)
        self.assertNotIn('更新された発信内容', home_after)
        self.assertIn('発令中の住民向け発信はありません', home_after)

    def test_unauthenticated_users_cannot_create_or_update_notices(self):
        app_module.instructions = [{
            'id': 9, 'target': '住民', 'content': '現行のお知らせ',
            'urgency': 'normal', 'status': '発令中',
        }]
        before = json.loads(json.dumps(app_module.instructions))
        create = self.client.post('/board', data={
            'target': '住民', 'content': '不正な書き換え', 'urgency': 'high', 'status': '発令中',
        })
        update = self.client.post('/board/9', data={
            'target': '住民', 'content': '不正な更新', 'urgency': 'high', 'status': '解除',
        })
        self.assertEqual(create.status_code, 302)
        self.assertEqual(update.status_code, 302)
        self.assertEqual(app_module.instructions, before)

    def test_main_pages_show_shared_navigation_and_current_page_state(self):
        pages = [
            ('/', None, 'ホーム'),
            ('/shelter_search', None, '避難所検索'),
            ('/search_results', None, '避難所検索'),
            ('/all_shelters', None, '避難所検索'),
            ('/shelter_register', True, '避難所登録'),
            ('/board', True, '指示・発信ボード'),
        ]
        for path, needs_login, active_label in pages:
            if needs_login:
                self.login()
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            body = response.get_data(as_text=True)
            self.assertIn('aria-label="メインメニュー"', body)
            self.assertIn(f'aria-current="page">{active_label}</a>', body)
            if needs_login:
                self.assertIn('href="/logout"', body)
            else:
                self.assertIn('href="/login"', body)
        self.client.get('/logout')
        unauthenticated = self.client.get('/shelter_search').get_data(as_text=True)
        self.assertIn('未ログイン', unauthenticated)
        self.assertIn('href="/login"', unauthenticated)
        login_page = self.client.get('/login').get_data(as_text=True)
        self.assertIn('aria-current="page">ログイン</a>', login_page)

    def test_home_renders_map_fallback_openstreetmap_attribution_and_accessible_markers(self):
        body = self.client.get('/').get_data(as_text=True)
        self.assertIn('青森市の避難所地図', body)
        self.assertIn('OpenStreetMap contributors', body)
        self.assertIn('対象地域の中心を表示しています', body)
        self.assertIn('getCurrentPosition', body)
        self.assertIn('開設中', body)
        self.assertIn('休止・未設定', body)
        self.assertIn('textContent = `${shelter.name}', body)

    def test_login_page_reports_missing_auth_configuration_using_config_flag(self):
        original = app_module.app.config['ADMIN_PASSWORD_CONFIGURED']
        try:
            app_module.app.config['ADMIN_PASSWORD_CONFIGURED'] = False
            body = self.client.get('/login').get_data(as_text=True)
            self.assertIn('ログイン認証が未設定です', body)
            app_module.app.config['ADMIN_PASSWORD_CONFIGURED'] = True
            body = self.client.get('/login').get_data(as_text=True)
            self.assertNotIn('ログイン認証が未設定です', body)
        finally:
            app_module.app.config['ADMIN_PASSWORD_CONFIGURED'] = original


if __name__ == '__main__':
    unittest.main()
