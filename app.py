from datetime import datetime, timedelta
import json
import os
import threading
import time
from bs4 import BeautifulSoup
from groq import Groq
import requests
import sqlite3
import streamlit as st

# --- 1. إعدادات الصفحة ---
st.set_page_config(
    page_title="CyberBel3arabi - AI Content Command Center",
    page_icon="🛡️",
    layout="wide",
)

GRAPH_API_VERSION = "v26.0"
DEFAULT_SOURCE_URL = (
    "https://www.staysafeonline.org/resources/online-safety-and-privacy/articles"
)
DB_PATH = "cyberbel3arabi.db"

# --- 1.5 نظام الحماية وتسجيل الدخول المعتمد على الـ Secrets ---


def check_password():

  def password_entered():
    try:
      admin_user = st.secrets["auth"]["admin_user"]
      admin_password = st.secrets["auth"]["admin_password"]
    except Exception:
      admin_user = "admin"
      admin_password = "12345"

    if (
        st.session_state.get("username") == admin_user
        and st.session_state.get("password") == admin_password
    ):
      st.session_state["password_correct"] = True
      st.session_state.pop("password", None)
      st.session_state.pop("username", None)
    else:
      st.session_state["password_correct"] = False

  if "password_correct" not in st.session_state:
    st.markdown("## 🔒 يرجى تسجيل الدخول للوصول إلى لوحة التحكم")
    st.text_input("اسم المستخدم", key="username")
    st.text_input("كلمة المرور", type="password", key="password")
    st.button("دخول", on_click=password_entered)
    return False
  elif not st.session_state["password_correct"]:
    st.markdown("## 🔒 يرجى تسجيل الدخول للوصول إلى لوحة التحكم")
    st.text_input("اسم المستخدم", key="username")
    st.text_input("كلمة المرور", type="password", key="password")
    st.button("دخول", on_click=password_entered)
    st.error("😕 اسم المستخدم أو كلمة المرور غير صحيحة")
    return False
  else:
    return True


if not check_password():
  st.stop()

# --- 2. إعداد قاعدة البيانات (SQLite) ---


def get_conn():
  return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
  conn = get_conn()
  cursor = conn.cursor()
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            topic TEXT,
            generated_post TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS automation_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
  conn.commit()
  conn.close()


def save_setting(key, value):
  conn = get_conn()
  cursor = conn.cursor()
  cursor.execute(
      "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
      (key, json.dumps(value)),
  )
  conn.commit()
  conn.close()


def load_setting(key, default_value):
  conn = get_conn()
  cursor = conn.cursor()
  cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
  result = cursor.fetchone()
  conn.close()
  if result:
    try:
      return json.loads(result[0])
    except Exception:
      return default_value
  return default_value


def is_duplicate(url, topic):
  if not url or not url.strip():
    return None
  conn = get_conn()
  cursor = conn.cursor()
  cursor.execute("SELECT id, topic FROM posts WHERE url = ?", (url.strip(),))
  result = cursor.fetchone()
  conn.close()
  return result


def save_post(url, topic, generated_post):
  conn = get_conn()
  cursor = conn.cursor()
  try:
    cursor.execute(
        "INSERT OR IGNORE INTO posts (url, topic, generated_post) VALUES (?, ?,"
        " ?)",
        (url.strip() if url else "", topic.strip(), generated_post),
    )
    conn.commit()
  except Exception as e:
    print(f"DB Error: {e}")
  finally:
    conn.close()


def get_recent_posts():
  conn = get_conn()
  cursor = conn.cursor()
  cursor.execute(
      "SELECT id, topic, url, created_at FROM posts ORDER BY id DESC LIMIT 10"
  )
  rows = cursor.fetchall()
  conn.close()
  return rows


def log_automation(message, status="info"):
  conn = get_conn()
  cursor = conn.cursor()
  cursor.execute(
      "INSERT INTO automation_log (message, status) VALUES (?, ?)",
      (message, status),
  )
  conn.commit()
  conn.close()


def get_automation_logs(limit=25):
  conn = get_conn()
  cursor = conn.cursor()
  cursor.execute(
      "SELECT message, status, created_at FROM automation_log ORDER BY id DESC"
      " LIMIT ?",
      (limit,),
  )
  rows = cursor.fetchall()
  conn.close()
  return rows


init_db()

# --- 3. سحب المقالات من المصدر ---


def scrape_articles(source_url=DEFAULT_SOURCE_URL):
  headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
  articles = []
  seen_links = set()

  try:
    res = requests.get(source_url, headers=headers, timeout=15)
    soup = BeautifulSoup(res.text, "html.parser")
    candidate_links = soup.find_all("a", href=True)

    for link in candidate_links:
      href = link["href"]
      if "/articles/" not in href:
        continue
      full_url = (
          href
          if href.startswith("http")
          else f"https://www.staysafeonline.org{href}"
      )
      if full_url in seen_links:
        continue

      container = link.find_parent(["div", "section", "article", "li"])
      title = ""
      summary = ""
      depth = 0
      probe = container
      while probe and depth < 5 and not title:
        heading = probe.find(["h1", "h2", "h3", "h4"])
        if heading:
          heading_text = heading.get_text(strip=True)
          if heading_text and len(heading_text) > 5:
            title = heading_text
            para = probe.find("p")
            if para:
              summary = para.get_text(strip=True)
            break
        probe = probe.find_parent(["div", "section", "article", "li"])
        depth += 1

      if title and full_url not in seen_links:
        seen_links.add(full_url)
        articles.append({"title": title, "url": full_url, "summary": summary})

    return articles
  except Exception as e:
    log_automation(f"فشل سحب المقالات: {str(e)}", "error")
    return []


def fetch_text_from_url(url):
  try:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    res = requests.get(url, headers=headers, timeout=10)
    res.encoding = "utf-8"
    soup = BeautifulSoup(res.text, "html.parser")
    for script in soup(["script", "style", "nav", "footer", "header"]):
      script.extract()
    paragraphs = [
        p.get_text().strip()
        for p in soup.find_all("p")
        if len(p.get_text().strip()) > 20
    ]
    return "\n".join(paragraphs)[:3000]
  except Exception as e:
    return f"ERROR: فشل جلب محتوى الرابط ({str(e)})"


# --- 4. فلترة الأهمية للناس العاديين عبر الذكاء الاصطناعي ---
def is_relevant_for_public(title, summary, api_key, model):
  try:
    client = Groq(api_key=api_key)
    prompt = f"""
        العنوان: {title}
        الملخص: {summary}
        هل هذا الموضوع مفيد وعملي للمستخدم العادي غير المتخصص تقنيًا؟ رد بكلمة واحدة فقط: نعم أو لا
        """
    result = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model=model,
    )
    answer = result.choices[0].message.content.strip().lower()
    return "نعم" in answer or "yes" in answer
  except Exception as e:
    log_automation(f"خطأ في فلترة الأهمية: {str(e)}", "error")
    return True


# --- 5. معالجة الصورة والتصميم ---
def process_arabic_text(text):
  import arabic_reshaper
  from bidi.algorithm import get_display

  reshaped_text = arabic_reshaper.reshape(text)
  return get_display(reshaped_text)


def get_text_width(draw, text, font):
  lines = text.split("\n")
  max_w = 0
  for line in lines:
    try:
      w = draw.textlength(line, font=font)
    except AttributeError:
      try:
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
      except Exception:
        w = len(line) * 15
    if w > max_w:
      max_w = w
  return max_w


def hex_to_rgb(hex_code):
  hex_code = hex_code.lstrip("#")
  return tuple(int(hex_code[i : i + 2], 16) for i in (0, 2, 4))


def create_image_template(
    title_text,
    points_list,
    title_color_hex,
    points_color_hex,
    title_font_size,
    points_font_size,
):
  from PIL import Image, ImageDraw, ImageFont

  # ضمان إنشاء مجلدات الإخراج والأصول محلياً ومطلقاً لتجنب اختفاء الصور
  base_dir = os.path.dirname(os.path.abspath(__file__))
  output_dir = os.path.join(base_dir, "output")
  os.makedirs(output_dir, exist_ok=True)

  template_path = os.path.join(base_dir, "assets", "template.png")
  font_path = os.path.join(base_dir, "assets", "Cairo-Bold.ttf")

  if os.path.exists(template_path):
    img = Image.open(template_path)
  else:
    img = Image.new("RGB", (1080, 1080), color=(15, 23, 42))

  draw = ImageDraw.Draw(img)

  try:
    title_font = ImageFont.truetype(font_path, title_font_size)
    points_font = ImageFont.truetype(font_path, points_font_size)
  except Exception:
    title_font = ImageFont.load_default()
    points_font = ImageFont.load_default()

  clean_title = title_text.replace("*", "").replace("•", "").strip()
  formatted_title = process_arabic_text(clean_title)

  cleaned_points = []
  for pt in points_list:
    p_clean = pt.replace("-", "").replace("*", "").strip()
    if p_clean:
      cleaned_points.append(process_arabic_text(f"• {p_clean}"))

  img_width, img_height = img.size
  line_spacing = 30
  total_block_height = title_font_size + line_spacing
  for _ in cleaned_points:
    total_block_height += points_font_size + line_spacing

  start_y = (img_height - total_block_height) / 2
  current_y = start_y

  title_rgb = hex_to_rgb(title_color_hex)
  points_rgb = hex_to_rgb(points_color_hex)

  title_width = get_text_width(draw, formatted_title, title_font)
  title_x = (img_width - title_width) / 2

  shadow_offset = 3
  draw.text(
      (title_x + shadow_offset, current_y + shadow_offset),
      formatted_title,
      font=title_font,
      fill=(0, 0, 0),
  )
  draw.text(
      (title_x, current_y), formatted_title, font=title_font, fill=title_rgb
  )

  current_y += title_font_size + line_spacing

  for pt in cleaned_points:
    pt_width = get_text_width(draw, pt, points_font)
    pt_x = (img_width - pt_width) / 2
    draw.text(
        (pt_x + shadow_offset, current_y + shadow_offset),
        pt,
        font=points_font,
        fill=(0, 0, 0),
    )
    draw.text((pt_x, current_y), pt, font=points_font, fill=points_rgb)
    current_y += points_font_size + line_spacing

  output_filename = f"streamlit_output_{int(time.time())}.png"
  output_path = os.path.join(output_dir, output_filename)
  img.save(output_path)
  return output_path


# --- 6. النشر عبر Facebook / Instagram Graph API ---
def publish_to_facebook_page(
    image_path, post_text, page_id, page_access_token
):
  if not page_id or not page_access_token:
    return {
        "status": "error",
        "message": "من فضلك أدخل Page ID و Page Access Token.",
    }
  if not os.path.exists(image_path):
    return {
        "status": "error",
        "message": f"لم يتم العثور على ملف الصورة: {image_path}",
    }

  url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{page_id}/photos"
  try:
    with open(image_path, "rb") as img_file:
      files = {"source": img_file}
      data = {
          "message": post_text,
          "access_token": page_access_token,
          "published": "true",
      }
      response = requests.post(url, data=data, files=files, timeout=30)
    result = response.json()
    if response.status_code == 200 and "id" in result:
      return {
          "status": "success",
          "message": f"تم النشر بنجاح! Post ID: {result['id']}",
      }
    else:
      error_msg = result.get("error", {}).get(
          "message", "خطأ غير معروف من فيسبوك"
      )
      return {"status": "error", "message": error_msg}
  except Exception as e:
    return {"status": "error", "message": str(e)}


# --- 7. خط الإنتاج الموحّد: توليد المحتوى + الصورة ---
def generate_content_and_image(
    content_source,
    api_key,
    model_choice,
    title_color,
    points_color,
    title_font_size,
    points_font_size,
):
  try:
    client = Groq(api_key=api_key)
    prompt = f"""
        أنت صانع محتوى ومحلل أمني لصفحة CyberBel3arabi. بناءً على المعطيات التالية:
        {content_source}
        اكتب بوست توعوي قصير، واجعل في نهاية الرد بالتنسيق التالي بدقة:
        TEMPLATE_TITLE: [عنوان رئيسي]
        TEMPLATE_POINTS:
        - [نقطة 1]
        - [نقطة 2]
        - [نقطة 3]
        """
    chat_completion = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model=model_choice,
    )
    raw_text = chat_completion.choices[0].message.content

    main_post_text = raw_text
    img_title = "حماية بياناتك تبدأ بالتوعية"
    img_points = [
        "تجنب الروابط الوهمية",
        "فعّل المصادقة الثنائية",
        "احمِ خصوصيتك الرقمية",
    ]

    if "TEMPLATE_TITLE:" in raw_text and "TEMPLATE_POINTS:" in raw_text:
      parts = raw_text.split("TEMPLATE_TITLE:")
      main_post_text = parts[0].strip()
      rest = parts[1]
      title_and_points = rest.split("TEMPLATE_POINTS:")
      img_title = title_and_points[0].strip()
      points_raw = title_and_points[1].strip()
      img_points = [
          p.replace("-", "").strip()
          for p in points_raw.split("\n")
          if p.strip()
      ]

    img_path = create_image_template(
        img_title,
        img_points,
        title_color,
        points_color,
        title_font_size,
        points_font_size,
    )

    return {
        "success": True,
        "main_post_text": main_post_text,
        "img_path": img_path,
        "raw_text": raw_text,
    }
  except Exception as e:
    return {"success": False, "error": str(e)}


def format_time_ampm(time_obj):
  hour = time_obj.hour
  minute = time_obj.minute
  period = "صباحًا" if hour < 12 else "مساءً"
  hour_12 = hour % 12
  if hour_12 == 0:
    hour_12 = 12
  return f"{hour_12:02d}:{minute:02d} {period}"


def format_date_arabic(date_str):
  try:
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return d.strftime("%d/%m/%Y")
  except Exception:
    return date_str


# --- 8. الجدولة التلقائية ---
@st.cache_resource
def get_scheduler_state():
  return {
      "thread": None,
      "stop_event": None,
      "status": "متوقف",
      "start_date": None,
      "end_date": None,
      "daily_time": None,
      "last_run_date": None,
  }


def scheduler_loop(
    stop_event, daily_time_str, start_date_str, end_date_str, config
):
  state = get_scheduler_state()
  while not stop_event.is_set():
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    current_time_str = now.strftime("%H:%M")

    if today_str > end_date_str:
      state["status"] = "انتهت المدة"
      break
    if today_str < start_date_str:
      time.sleep(20)
      continue

    if (
        current_time_str == daily_time_str
        and state.get("last_run_date") != today_str
    ):
      try:
        articles = scrape_articles(config["source_url"])
        for art in articles:
          if is_duplicate(art["url"], art["title"]):
            continue
          if not is_relevant_for_public(
              art["title"],
              art["summary"],
              config["api_key"],
              config["model_choice"],
          ):
            continue
          content_source = (
              f"العنوان: {art['title']}\nالملخص: {art['summary']}\nالمصدر:"
              f" {art['url']}"
          )
          gen = generate_content_and_image(
              content_source,
              config["api_key"],
              config["model_choice"],
              config["title_color"],
              config["points_color"],
              config["title_font_size"],
              config["points_font_size"],
          )
          if gen["success"]:
            save_post(art["url"], art["title"], gen["raw_text"])
            publish_to_facebook_page(
                gen["img_path"],
                gen["main_post_text"],
                config["fb_page_id"],
                config["fb_page_token"],
            )
            break
      except Exception as e:
        log_automation(str(e), "error")
      state["last_run_date"] = today_str
    time.sleep(20)
  state["status"] = "متوقف"


def start_scheduler(
    start_date_str, end_date_str, daily_time_str, daily_time_display, config
):
  state = get_scheduler_state()
  if state["thread"] is not None and state["thread"].is_alive():
    return False
  stop_event = threading.Event()
  thread = threading.Thread(
      target=scheduler_loop,
      args=(
          stop_event,
          daily_time_str,
          start_date_str,
          end_date_str,
          config,
      ),
      daemon=True,
  )
  state["thread"] = thread
  state["stop_event"] = stop_event
  state["status"] = "شغال"
  state["start_date"] = start_date_str
  state["end_date"] = end_date_str
  state["daily_time"] = daily_time_display
  state["last_run_date"] = None
  thread.start()
  return True


def stop_scheduler():
  state = get_scheduler_state()
  if state["stop_event"] is not None:
    state["stop_event"].set()
  state["status"] = "متوقف"


# --- 9. القائمة الجانبية للإعدادات ---
with st.sidebar:
  if os.path.exists("assets/logo.png"):
    st.image("assets/logo.png", width=100)
  else:
    st.image("https://img.icons8.com/color/96/shield.png", width=64)

  st.title("CyberBel3arabi Settings")
  api_key = st.text_input("Groq API Key", type="password")
  model_choice = st.selectbox(
      "نموذج الذكاء الاصطناعي",
      [
          "openai/gpt-oss-120b",
          "llama-3.3-70b-versatile",
          "qwen/qwen3.8-27b",
          "llama-3.1-8b-instant",
      ],
  )

  st.markdown("---")
  fb_page_id = st.text_input("Facebook Page ID")
  fb_page_token = st.text_input("Page Access Token", type="password")

  saved_title_color = load_setting("title_color", "#FFD700")
  saved_points_color = load_setting("points_color", "#FFFFFF")
  saved_title_size = load_setting("title_size", 60)
  saved_points_size = load_setting("points_size", 50)

  title_color = st.color_picker("لون العنوان الرئيسي", value=saved_title_color)
  points_color = st.color_picker("لون نقاط المحتوى", value=saved_points_color)
  title_font_size = st.slider(
      "حجم خط العنوان", min_value=30, max_value=100, value=saved_title_size
  )
  points_font_size = st.slider(
      "حجم خط النقاط", min_value=20, max_value=80, value=saved_points_size
  )

  if st.button("💾 حفظ الإعدادات", use_container_width=True):
    save_setting("title_color", title_color)
    save_setting("points_color", points_color)
    save_setting("title_size", title_font_size)
    save_setting("points_size", points_font_size)
    st.toast("✅ تم الحفظ بنجاح!", icon="💾")

# --- 10. الواجهة الرئيسية ---
st.title("🛡️ CyberBel3arabi — Content Command Center")
tabs = st.tabs(["🚀 توليد محتوى يدوي", "⏰ الجدولة التلقائية", "📂 سجل المواضيع"])

# === Tab 1: توليد المحتوى ===
with tabs[0]:
  col_in1, col_in2 = st.columns([2, 1])
  with col_in1:
    url_input = st.text_input("🔗 رابط مقال / خبر توعوي (URL):")
    topic_input = st.text_area("📝 أو اكتب الموضوع مباشرة:")
  with col_in2:
    st.markdown("### ⚙️ إجراءات")
    generate_btn = st.button(
        "⚡ توليد البوست والتصميم", type="primary", use_container_width=True
    )

  if generate_btn:
    if not api_key:
      st.error("❌ يرجى إدخال Groq API Key.")
    elif not url_input and not topic_input:
      st.warning("يرجى إدخال رابط أو موضوع للتوليد.")
    else:
      with st.spinner("🔄 جاري التوليد..."):
        if url_input.strip():
          extracted = fetch_text_from_url(url_input)
          content_source = f"المحتوى المستخرج من الرابط:\n{extracted}"
        else:
          content_source = f"الموضوع: {topic_input}"

        gen = generate_content_and_image(
            content_source,
            api_key,
            model_choice,
            title_color,
            points_color,
            title_font_size,
            points_font_size,
        )

        if gen["success"]:
          save_post(url_input, topic_input or "مقال من رابط", gen["raw_text"])
          st.success("🎉 تم توليد التصميم بدقة بنجاح!")
          st.session_state["generated_post_text"] = gen["main_post_text"]
          st.session_state["generated_img_path"] = gen["img_path"]
        else:
          st.error(f"خطأ أثناء التوليد: {gen['error']}")

  if (
      "generated_post_text" in st.session_state
      and "generated_img_path" in st.session_state
  ):
    st.markdown("---")
    res_col1, res_col2 = st.columns([3, 2])
    with res_col1:
      st.text_area(
          "محتوى البوست الجاهز:",
          value=st.session_state["generated_post_text"],
          height=250,
          key="editable_post",
      )
      if st.button("🚀 انشر الآن على فيسبوك", type="primary"):
        res = publish_to_facebook_page(
            st.session_state["generated_img_path"],
            st.session_state["editable_post"],
            fb_page_id,
            fb_page_token,
        )
        if res["status"] == "success":
          st.success(res["message"])
        else:
          st.error(res["message"])
    with res_col2:
      st.subheader("🖼️ معاينة التصميم النهائي")
      current_img = st.session_state["generated_img_path"]
      if current_img and os.path.exists(current_img):
        st.image(current_img, use_container_width=True)
      else:
        st.warning(
            "تعذر العثور على ملف الصورة المعروضة، يرجى إعادة التوليد."
        )

# === Tab 2: الجدولة ===
with tabs[1]:
  st.subheader("⏰ التشغيل الأوتوماتيكي")
  scheduler_state = get_scheduler_state()
  is_running = (
      scheduler_state["thread"] is not None
      and scheduler_state["thread"].is_alive()
  )
  source_url = st.text_input(
      "🔗 رابط صفحة المقالات:", value=DEFAULT_SOURCE_URL
  )
  start_date = st.date_input("من تاريخ:", value=datetime.now().date())
  end_date = st.date_input(
      "إلى تاريخ:", value=datetime.now().date() + timedelta(days=7)
  )
  daily_time = st.time_input(
      "اختر الوقت:", value=datetime.strptime("10:00", "%H:%M").time()
  )

  if st.button("▶️ ابدأ التشغيل الأوتوماتيكي", type="primary"):
    if api_key and fb_page_id and fb_page_token:
      config = {
          "source_url": source_url,
          "api_key": api_key,
          "model_choice": model_choice,
          "title_color": title_color,
          "points_color": points_color,
          "title_font_size": title_font_size,
          "points_font_size": points_font_size,
          "fb_page_id": fb_page_id,
          "fb_page_token": fb_page_token,
      }
      start_scheduler(
          start_date.strftime("%Y-%m-%d"),
          end_date.strftime("%Y-%m-%d"),
          daily_time.strftime("%H:%M"),
          format_time_ampm(daily_time),
          config,
      )
      st.success("✅ تم التفعيل!")
      st.rerun()
    else:
      st.error("أدخل بيانات API و Facebook أولاً.")

  if st.button("⏹️ إيقاف التشغيل الأوتوماتيكي"):
    stop_scheduler()
    st.success("تم التوقف.")
    st.rerun()

# === Tab 3: السجل ===
with tabs[2]:
  st.subheader("📂 سجل المواضيع والروابط المنشورة")
  rows = get_recent_posts()
  if rows:
    st.dataframe(rows, hide_index=True, use_container_width=True)
  else:
    st.info("لا توجد سجلات محفوظة.")
