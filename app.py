from flask import Flask, jsonify, request, render_template, session, redirect, url_for
from urllib.parse import urlparse, urljoin
from functools import wraps
from html.parser import HTMLParser
import json
import os
import secrets
import urllib.request
from datetime import datetime, timedelta, timezone

# app.py はプロジェクト直下に置く。
# 実体（templates / static / data）は bousai_app/ 配下にあるので、そこを参照する。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, 'bousai_app')

app = Flask(
    __name__,
    template_folder=os.path.join(APP_DIR, 'templates'),
    static_folder=os.path.join(APP_DIR, 'static'),
)
app.secret_key = os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32)

# 管理者認証情報は環境変数から取得する
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')
app.config['ADMIN_PASSWORD_CONFIGURED'] = bool(ADMIN_PASSWORD)

# ────────────────────────────────
# 気象警報・注意報設定
PREFECTURE_CODE = "020000"  # 青森県
AREA_NAME = "青森市"

# 青森市の市区町村コード
AREA_CODE = "0220100"
app.config['AREA_NAME'] = AREA_NAME

WARNING_URL = (
    f"https://www.jma.go.jp/bosai/warning/data/r8/{PREFECTURE_CODE}.json"
)
CITY_DISASTER_URL = (
    "https://www.city.aomori.aomori.jp/anzen_kinkyu/saigai/1002513.html"
)
CITY_CENTER = (40.8222, 140.7474)
MAX_JMA_REPORT_AGE = timedelta(hours=48)

JST = timezone(timedelta(hours=9))

# 警報・注意報のコード一覧
WARNING_CODES = {
    "00": "解除",
    "02": "暴風雪警報",
    "03": "レベル3大雨警報",
    "04": "洪水警報",
    "05": "暴風警報",
    "06": "大雪警報",
    "07": "波浪警報",
    "08": "レベル3高潮警報",
    "09": "レベル3土砂災害警報",
    "10": "レベル2大雨注意報",
    "12": "大雪注意報",
    "13": "風雪注意報",
    "14": "雷注意報",
    "15": "強風注意報",
    "16": "波浪注意報",
    "17": "融雪注意報",
    "18": "洪水注意報",
    "19": "レベル2高潮注意報",
    "20": "濃霧注意報",
    "21": "乾燥注意報",
    "22": "なだれ注意報",
    "23": "低温注意報",
    "24": "霜注意報",
    "25": "着氷注意報",
    "26": "着雪注意報",
    "27": "その他の注意報",
    "29": "レベル2土砂災害注意報",
    "32": "暴風雪特別警報",
    "33": "レベル5大雨特別警報",
    "35": "暴風特別警報",
    "36": "大雪特別警報",
    "37": "波浪特別警報",
    "38": "レベル5高潮特別警報",
    "39": "レベル5土砂災害特別警報",
    "43": "レベル4大雨危険警報",
    "48": "レベル4高潮危険警報",
    "49": "レベル4土砂災害危険警報"
}

SHELTER_STATUSES = ("未設定", "開設中", "閉鎖")
FACILITY_SUPPORT_VALUES = ("unknown", "yes", "no")

# ────────────────────────────────
# サンプルデータの読み込み
DATA_FILE = os.path.join(APP_DIR, 'data', 'shelters.json')
INSTRUCTIONS_FILE = os.path.join(APP_DIR, 'data', 'instructions.json')

def load_json(path, default):
    """JSONファイルを読み込む（存在しない・壊れている場合は default を返す）"""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

shelters = load_json(DATA_FILE, [])
instructions = load_json(INSTRUCTIONS_FILE, [])

def save_instructions():
    """指示ボードのデータをファイルに保存する"""
    with open(INSTRUCTIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(instructions, f, ensure_ascii=False, indent=2)


def save_shelters():
    """避難所データをファイルに保存する"""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(shelters, f, ensure_ascii=False, indent=2)
# ────────────────────────────────

# ────────────────────────────────
# 認証関連の設定とヘルパー関数
def is_safe_url(target):
    """リダイレクト先URLが安全かどうかチェック"""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

def login_required(f):
    """認証が必要なページに付けるデコレータ"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            # 現在のURLをnextパラメータとしてログイン画面にリダイレクト
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def get_japan_time():
    """日本時間（JST）の現在時刻を取得する"""
    return datetime.now(JST).strftime("%Y年%m月%d日 %H:%M")


def format_report_time(iso_str):
    """気象庁の発表時刻（ISO形式）をJSTの表示用文字列に変換する"""
    if not iso_str:
        return "不明"
    try:
        parsed = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        if parsed.tzinfo:
            parsed = parsed.astimezone(JST)
        return parsed.strftime("%Y年%m月%d日 %H:%M")
    except ValueError:
        return iso_str


def filter_shelters(district=None):
    """district 指定があれば一致する避難所のみ、なければ全件を返す"""
    return [s for s in shelters if not district or s.get('district') == district]


def valid_coordinates(latitude, longitude):
    """緯度経度が数値かつ地理的な範囲内であることを確認する"""
    if isinstance(latitude, bool) or isinstance(longitude, bool):
        return False
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        return False
    return (
        -90 <= latitude <= 90
        and -180 <= longitude <= 180
    )


def get_map_shelters():
    """座標を持つ避難所だけを地図API用に返す"""
    result = []
    for shelter in shelters if isinstance(shelters, list) else []:
        if not isinstance(shelter, dict):
            continue
        if shelter.get('verified') is not True:
            continue
        shelter_id = shelter.get('id')
        name = shelter.get('name')
        if (
            isinstance(shelter_id, bool)
            or not isinstance(shelter_id, (int, str))
            or not str(shelter_id).strip()
            or not isinstance(name, str)
            or not name.strip()
        ):
            continue
        latitude = shelter.get('latitude', shelter.get('lat'))
        longitude = shelter.get('longitude', shelter.get('lon'))
        if not valid_coordinates(latitude, longitude):
            continue
        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (TypeError, ValueError):
            continue
        result.append({
            'id': shelter_id,
            'name': name.strip(),
            'status': shelter.get('status')
            if shelter.get('status') in SHELTER_STATUSES
            else '未設定',
            'latitude': latitude,
            'longitude': longitude,
            'district': shelter.get('district', ''),
            'verified': True,
        })
    return result


def validate_jma_report_freshness(report_datetime, now=None):
    """古い気象庁データを現在の情報として扱わない"""
    if not report_datetime:
        raise ValueError('気象庁データに発表時刻がありません')
    try:
        reported_at = datetime.fromisoformat(report_datetime.replace('Z', '+00:00'))
    except (AttributeError, ValueError) as error:
        raise ValueError('気象庁データの発表時刻を解析できません') from error
    if reported_at.tzinfo is None:
        raise ValueError('気象庁データの発表時刻にタイムゾーンがありません')
    current_time = now or datetime.now(JST)
    age = current_time - reported_at.astimezone(JST)
    if age < timedelta(minutes=-5):
        raise ValueError('気象庁データの発表時刻が未来です')
    if age > MAX_JMA_REPORT_AGE:
        raise ValueError('気象庁データが古いため最新情報を確認できません')


class CityDisasterPageParser(HTMLParser):
    """青森市公式ページの本文から、ページ付帯情報を除いてテキストを得る"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_content = False
        self.content_depth = 0
        self.ignored_depth = 0
        self.element_stack = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'article' and attributes.get('id') == 'content':
            self.in_content = True
            self.content_depth = 1
            return
        if not self.in_content:
            return

        classes = attributes.get('class', '').split()
        ignored = (
            attributes.get('id') == 'reference'
            or 'box' in classes
            or tag in ('script', 'style', 'h1')
        )
        if tag not in ('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'):
            self.element_stack.append((tag, ignored))
            self.content_depth += 1
            if ignored:
                self.ignored_depth += 1

    def handle_endtag(self, tag):
        if not self.in_content:
            return
        if tag == 'article' and self.content_depth == 1:
            self.in_content = False
            return
        for index in range(len(self.element_stack) - 1, -1, -1):
            if self.element_stack[index][0] == tag:
                removed = self.element_stack[index:]
                del self.element_stack[index:]
                self.content_depth -= len(removed)
                self.ignored_depth -= sum(1 for _, ignored in removed if ignored)
                break

    def handle_data(self, data):
        if self.in_content and not self.ignored_depth:
            text = ' '.join(data.split())
            if text:
                self.parts.append(text)

    def result(self):
        return ' '.join(self.parts).strip()


def parse_city_disaster_page(html):
    """公式ページ本文を解析し、本文構造の変更を検知する"""
    parser = CityDisasterPageParser()
    parser.feed(html)
    text = parser.result()
    if not text:
        raise ValueError('青森市公式ページの本文を確認できません')
    if '現在、情報はありません' in text:
        return {'status': 'none', 'content': ''}
    category = (
        '緊急' if any(term in text for term in ('避難指示', '緊急安全確保', '特別警報'))
        else '警報' if '警報' in text
        else '注意報' if '注意報' in text
        else '通常'
    )
    return {'status': 'active', 'content': text, 'category': category}


def fetch_city_disaster_information():
    try:
        request_object = urllib.request.Request(
            CITY_DISASTER_URL,
            headers={'User-Agent': 'BousaiApp/1.0'},
        )
        with urllib.request.urlopen(request_object, timeout=10) as response:
            html = response.read().decode('utf-8')
        result = parse_city_disaster_page(html)
        return {
            **result,
            'area_name': AREA_NAME,
            'source_url': CITY_DISASTER_URL,
            'checked_at': get_japan_time(),
        }
    except (OSError, UnicodeError, ValueError) as error:
        app.logger.warning('青森市公式災害情報の取得・解析に失敗しました: %s', error)
        return {
            'status': 'error',
            'content': '',
            'area_name': AREA_NAME,
            'source_url': CITY_DISASTER_URL,
            'checked_at': get_japan_time(),
        }


def parse_area_warnings(warning_data):
    """気象庁の新形式JSONから対象市区町村の発表・継続中の情報を抽出する"""
    if not isinstance(warning_data, list):
        raise ValueError("気象庁の警報・注意報データが新形式の配列ではありません")

    active_warnings = {}
    area_reports = []

    for report in warning_data:
        if not isinstance(report, dict):
            continue

        report_datetime = report.get("reportDatetime")
        warning = report.get("warning")
        if not isinstance(warning, dict):
            continue

        class20_items = warning.get("class20Items", [])
        if not isinstance(class20_items, list):
            continue

        area = next(
            (
                item for item in class20_items
                if isinstance(item, dict)
                and item.get("areaCode") == AREA_CODE
            ),
            None
        )
        if not area:
            continue

        kinds = area.get("kinds", [])
        if not isinstance(kinds, list):
            continue
        area_reports.append((
            report_datetime if isinstance(report_datetime, str) else "",
            kinds
        ))

    if not area_reports:
        raise ValueError(f"気象庁データに対象地域 {AREA_CODE} がありません")

    for _, kinds in sorted(area_reports, key=lambda item: item[0]):
        for kind in kinds:
            if not isinstance(kind, dict):
                continue

            status = kind.get("status", "")
            code = kind.get("code", "")
            if status == "発表警報・注意報はなし":
                active_warnings.clear()
                continue

            if not code:
                continue
            if status in ("発表", "継続"):
                active_warnings[code] = status
            elif status == "解除":
                active_warnings.pop(code, None)

    warnings = []
    for code, status in active_warnings.items():
        name = WARNING_CODES.get(code, f"不明な警報・注意報 (コード: {code})")
        category = (
            '緊急' if '特別警報' in name or '危険警報' in name
            else '警報' if '警報' in name
            else '注意報'
        )
        warnings.append({
            'name': name,
            'code': code,
            'status': status,
            'category': category,
            'area_name': AREA_NAME,
        })
    warnings.sort(key=lambda item: (item['category'] != '緊急', item['category'] != '警報', item['name']))
    latest_report_datetime = max(
        (report_datetime for report_datetime, _ in area_reports),
        default=""
    )
    return warnings, latest_report_datetime


def get_weather_warnings():
    """対象市区町村の警報・注意報を取得する"""
    try:
        # 青森県の新形式（令和8年～）警報・注意報データを取得
        request_object = urllib.request.Request(
            WARNING_URL,
            headers={'User-Agent': 'BousaiApp/1.0'},
        )
        with urllib.request.urlopen(request_object, timeout=10) as res:
            warning_data = json.loads(res.read().decode('utf-8'))

        warnings, report_datetime = parse_area_warnings(warning_data)
        validate_jma_report_freshness(report_datetime)

        return {
            "area_name": AREA_NAME,
            "warnings": warnings,
            "report_time": format_report_time(report_datetime),
            "last_fetch_time": get_japan_time(),
            "source_url": WARNING_URL,
        }

    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        app.logger.warning('気象庁警報・注意報の取得・解析に失敗しました: %s', error)
        return {
            "area_name": AREA_NAME,
            "warnings": [],
            "report_time": "確認できません",
            "last_fetch_time": get_japan_time(),
            "source_url": WARNING_URL,
            "error_message": str(error),
            "error": True
        }


# トップページ：templates/index.html を返す（住民向け指示も表示する）
@app.route('/')
def index():
    resident_notices = sorted(
        (i for i in instructions if i.get('target') == '住民'),
        key=lambda item: item.get('updated_at', ''),
        reverse=True,
    )
    return render_template(
        'index.html',
        resident_notices=resident_notices,
        city_center=CITY_CENTER,
    )

# ログインページ
@app.route('/login', methods=['GET', 'POST'])
def login():
    # リダイレクト先を取得（デフォルトは避難所登録画面）
    next_url = request.args.get('next') or request.form.get('next')

    # 安全でないURLの場合はデフォルトページにリダイレクト
    if not next_url or not is_safe_url(next_url):
        next_url = url_for('shelter_register')

    if request.method == 'POST':
        password = request.form.get('password', '').strip()

        # 認証チェック
        username = (
            ADMIN_USERNAME
            if ADMIN_PASSWORD and secrets.compare_digest(password, ADMIN_PASSWORD)
            else None
        )
        if username:
            session['logged_in'] = True
            session['username'] = username
            # ログイン成功後は指定されたページにリダイレクト
            return redirect(next_url)
        return render_template('login.html', error=True, message="パスワードが正しくありません。", next=next_url)

    # ログイン済みの場合は指定されたページにリダイレクト
    if session.get('logged_in'):
        return redirect(next_url)

    return render_template('login.html', next=next_url)

# ログアウト
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# 避難所登録ページ
@app.route('/shelter_register', methods=['GET', 'POST'])
@login_required
def shelter_register():
    if request.method == 'POST':
        shelter_name = request.form.get('name', '').strip()
        shelter_address = request.form.get('address', '').strip()
        shelter_status = request.form.get('status', '未設定').strip()
        capacity_input = request.form.get('capacity', '').strip()
        evacuees_input = request.form.get('evacuees', '').strip()
        pets_allowed = request.form.get('pets_allowed', 'unknown').strip()
        barrier_free = request.form.get('barrier_free', 'unknown').strip()
        district = request.form.get('district', '').strip()
        latitude_input = request.form.get('latitude', '').strip()
        longitude_input = request.form.get('longitude', '').strip()
        verified = request.form.get('verified') == 'yes'

        if not shelter_name:
            return render_template(
                'shelter_register.html',
                error=True,
                message='避難所名を入力してください'
            )

        if shelter_status not in SHELTER_STATUSES:
            return render_template(
                'shelter_register.html',
                error=True,
                message='開設状況を選択してください。'
            ), 400

        if (
            pets_allowed not in FACILITY_SUPPORT_VALUES
            or barrier_free not in FACILITY_SUPPORT_VALUES
        ):
            return render_template(
                'shelter_register.html',
                error=True,
                message='設備・対応状況の値が正しくありません。'
            ), 400

        try:
            capacity = int(capacity_input) if capacity_input else None
            evacuees = int(evacuees_input) if evacuees_input else None
        except ValueError:
            return render_template(
                'shelter_register.html',
                error=True,
                message='収容人数と現在の避難者数は整数で入力してください。'
            ), 400

        if capacity is not None and capacity < 1:
            return render_template(
                'shelter_register.html',
                error=True,
                message='収容人数は1人以上で入力してください。'
            ), 400

        if evacuees is not None and evacuees < 0:
            return render_template(
                'shelter_register.html',
                error=True,
                message='現在の避難者数は0人以上で入力してください。'
            ), 400

        if bool(latitude_input) != bool(longitude_input):
            return render_template(
                'shelter_register.html',
                error=True,
                message='緯度と経度は両方入力してください。'
            ), 400
        latitude = longitude = None
        if latitude_input:
            if not valid_coordinates(latitude_input, longitude_input):
                return render_template(
                    'shelter_register.html',
                    error=True,
                    message='緯度・経度は有効な数値で入力してください。'
                ), 400
            latitude = float(latitude_input)
            longitude = float(longitude_input)

        if verified and latitude is None:
            return render_template(
                'shelter_register.html',
                error=True,
                message='確認済みとして登録するには緯度・経度を入力してください。'
            ), 400

        if (
            len(shelter_name) > 200
            or len(shelter_address) > 300
            or len(district) > 100
        ):
            return render_template(
                'shelter_register.html',
                error=True,
                message='名称・住所・地区の入力文字数を確認してください。'
            ), 400

        existing_ids = (
            s.get('id')
            for s in shelters
            if isinstance(s, dict)
            and isinstance(s.get('id'), int)
            and not isinstance(s.get('id'), bool)
        )
        new_id = max(existing_ids, default=0) + 1
        new_shelter = {
            'id': new_id,
            'name': shelter_name,
            'address': shelter_address,
            'district': district,
            'status': shelter_status,
            'capacity': capacity,
            'evacuees': evacuees,
            'pets_allowed': pets_allowed,
            'barrier_free': barrier_free,
            'latitude': latitude,
            'longitude': longitude,
            'verified': verified,
        }
        shelters.append(new_shelter)
        try:
            save_shelters()
        except OSError:
            shelters.pop()
            app.logger.exception('避難所データの保存に失敗しました')
            return render_template(
                'shelter_register.html',
                error=True,
                message='避難所を保存できませんでした。時間をおいて再度お試しください。'
            ), 500

        return render_template(
            'shelter_register.html',
            success=True,
            message='避難所を登録しました'
        )

    return render_template('shelter_register.html')

# 避難所検索ページ
@app.route('/shelter_search')
def shelter_search():
    return render_template(
        'shelter_search.html',
        district=request.args.get('district', '').strip()
    )

# 全施設一覧ページ
@app.route('/all_shelters')
def all_shelters():
    return render_template('search_results.html', results=shelters)


# 指示ボード：住民向けの指示を一覧で確認する
@app.route('/board')
@login_required
def board():
    board_instructions = sorted(
        instructions,
        key=lambda item: item.get('updated_at', ''),
        reverse=True,
    )
    return render_template('board.html', instructions=board_instructions)


@app.route('/board', methods=['POST'])
@login_required
def create_instruction():
    target = request.form.get('target', '').strip()
    content = request.form.get('content', '').strip()
    shelter = request.form.get('shelter', '').strip()
    urgency = request.form.get('urgency', 'normal').strip()
    status = request.form.get('status', '発令中').strip()
    if (
        target not in ('住民', '運営者')
        or not content
        or len(content) > 2000
        or len(shelter) > 200
        or urgency not in ('high', 'normal')
        or status not in ('発令中', '解除', '完了')
    ):
        return redirect(url_for('board', error='invalid'))

    now = datetime.now(JST).isoformat(timespec='minutes')
    item = {
        'id': max(
            (
                i.get('id')
                for i in instructions
                if isinstance(i, dict)
                and isinstance(i.get('id'), int)
                and not isinstance(i.get('id'), bool)
            ),
            default=0,
        ) + 1,
        'target': target,
        'content': content,
        'shelter': shelter,
        'urgency': urgency,
        'status': status,
        'created_at': now,
        'updated_at': now,
        'author': session.get('username', ADMIN_USERNAME),
    }
    instructions.append(item)
    try:
        save_instructions()
    except OSError:
        instructions.pop()
        app.logger.exception('住民向け発信の保存に失敗しました')
        return redirect(url_for('board', error='save'))
    return redirect(url_for('board', saved='1'))


@app.route('/board/<int:instruction_id>', methods=['POST'])
@login_required
def update_instruction(instruction_id):
    item = next((entry for entry in instructions if entry.get('id') == instruction_id), None)
    if item is None:
        return redirect(url_for('board', error='not-found'))
    previous = item.copy()
    target = request.form.get('target', '').strip()
    content = request.form.get('content', '').strip()
    shelter = request.form.get('shelter', '').strip()
    urgency = request.form.get('urgency', '').strip()
    status = request.form.get('status', '').strip()
    if (
        target not in ('住民', '運営者')
        or not content
        or len(content) > 2000
        or len(shelter) > 200
        or urgency not in ('high', 'normal')
        or status not in ('発令中', '解除', '完了')
    ):
        return redirect(url_for('board', error='invalid'))
    item.update({
        'target': target,
        'content': content,
        'shelter': shelter,
        'urgency': urgency,
        'status': status,
        'updated_at': datetime.now(JST).isoformat(timespec='minutes'),
    })
    try:
        save_instructions()
    except OSError:
        item.clear()
        item.update(previous)
        app.logger.exception('住民向け発信の更新に失敗しました')
        return redirect(url_for('board', error='save'))
    return redirect(url_for('board', saved='1'))

# 検索結果ページ：templates/search_results.html を返す
@app.route('/search_results')
def search_results():
    district = request.args.get('district', '').strip()
    results = filter_shelters(district)
    return render_template(
        'search_results.html',
        results=results,
        searched_district=district
    )

# JSON API：/shelters?district=地区名
@app.route('/shelters', methods=['GET'])
def get_shelters():
    results = filter_shelters(request.args.get('district'))

    return jsonify([
        {**shelter, 'verified': shelter.get('verified') is True}
        for shelter in results
        if isinstance(shelter, dict)
    ])


@app.route('/api/shelters', methods=['GET'])
def api_map_shelters():
    map_shelters = get_map_shelters()
    return jsonify({
        'area_name': AREA_NAME,
        'shelters': map_shelters,
        'status': 'ok' if map_shelters else 'empty',
    })


# 気象警報・注意報API
@app.route('/api/weather_warnings')
def api_weather_warnings():
    """気象警報・注意報をJSON形式で返すAPI"""
    return jsonify(get_weather_warnings())


@app.route('/api/public_disaster_information')
def api_public_disaster_information():
    return jsonify({
        'municipal': fetch_city_disaster_information(),
        'weather': get_weather_warnings(),
        'area_name': AREA_NAME,
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)
