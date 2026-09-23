import os
import requests
import sqlite3
import streamlit as st

# إعدادات الصفحة الأساسية
st.set_page_config(
    page_title="CyberBel3arabi Dashboard", page_icon="🛡️", layout="wide"
)

# --- 1. نظام الحماية وتسجيل الدخول المعتمد على الـ Secrets ---


def check_password():

  def password_entered():
    try:
      admin_user = st.secrets["auth"]["admin_user"]
      admin_password = st.secrets["auth"]["admin_password"]
    except Exception:
      # قيم افتراضية طارئة لو ملف الـ secrets مش مظبوط
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

# --- 2. إعداد قاعدة البيانات المحلية SQLite ---
DB_FILE = "cyberbel3arabi.db"


def init_db():
  conn = sqlite3.connect(DB_FILE)
  cursor = conn.cursor()
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT,
            status TEXT
        )
    """)
  conn.commit()
  conn.close()


init_db()

# --- 3. دالة النشر السحابي عبر Meta Graph API ---


def publish_to_facebook_api(message, image_path=None):
  try:
    page_id = st.secrets["facebook"]["page_id"]
    access_token = st.secrets["facebook"]["access_token"]
  except Exception as e:
    st.error(f"❌ بيانات فيسبوك غير متوفرة في الـ Secrets: {e}")
    return

  if image_path and os.path.exists(image_path):
    url = f"https://graph.facebook.com/{page_id}/photos"
    payload = {"message": message, "access_token": access_token}
    try:
      with open(image_path, "rb") as image_file:
        files = {"source": image_file}
        response = requests.post(url, data=payload, files=files)
      result = response.json()
      if "id" in result:
        st.success("🎉 تم نشر الصورة والنص على الفيسبوك بنجاح عبر السحاب!")
      else:
        st.error(f"❌ خطأ أثناء النشر: {result.get('error', {}).get('message')}")
    except Exception as e:
      st.error(f"❌ حدث خطأ في رفع الصورة: {e}")
  else:
    url = f"https://graph.facebook.com/{page_id}/feed"
    payload = {"message": message, "access_token": access_token}
    try:
      response = requests.post(url, data=payload)
      result = response.json()
      if "id" in result:
        st.success("🎉 تم نشر المنشور على الفيسبوك بنجاح عبر السحاب!")
      else:
        st.error(f"❌ خطأ أثناء النشر: {result.get('error', {}).get('message')}")
    except Exception as e:
      st.error(f"❌ حدث خطأ في الاتصال: {e}")


# --- 4. واجهة المستخدم الرئيسية للتطبيق ---
st.title("🛡️ CyberBel3arabi Dashboard")
st.markdown("لوحة التحكم السحابية لإدارة وتوليد ونشر المحتوى الأمني.")

menu = ["توليد المحتوى", "النشر السحابي", "أرشيف المنشورات"]
choice = st.sidebar.selectbox("القائمة الرئيسية", menu)

if choice == "توليد المحتوى":
  st.subheader("🤖 توليد منشور توعوي بالذكاء الاصطناعي")
  topic = st.text_input("موضوع المنشور (مثال: الأمان على شبكات الواي فاي العامة)")
  if st.button("توليد النص"):
    if topic:
      with st.spinner("جاري التوليد عبر الذكاء الاصطناعي..."):
        # محاكاة توليد النص أو ربطه بـ Groq API حسب رغبتك
        generated_text = (
            f"⚠️ تحذير أمني مهم بخصوص: {topic}\n\nاحذر دائماً من..."
        )
        st.success("تم التوليد بنجاح!")
        st.text_area("النص الناتج:", value=generated_text, height=150)
    else:
      st.warning("يرجى كتابة الموضوع أولاً.")

elif choice == "النشر السحابي":
  st.subheader("🚀 النشر الفوري على صفحة فيسبوك")
  post_text = st.text_area("نص المنشور المراد نشره:")
  uploaded_image = st.file_uploader(
      "اختر صورة مرفقة (اختياري)", type=["png", "jpg", "jpeg"]
  )

  image_path = None
  if uploaded_image is not None:
    image_path = "temp_image.png"
    with open(image_path, "wb") as f:
      f.write(uploaded_image.getbuffer())

  if st.button("نشر الآن 🌐"):
    if post_text:
      with st.spinner("جاري إرسال المنشور عبر السحاب..."):
        publish_to_facebook_api(post_text, image_path)

        # حفظ المنشور في قاعدة البيانات المحلية
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO posts (content, status) VALUES (?, ?)",
            (post_text, "Published"),
        )
        conn.commit()
        conn.close()
    else:
      st.warning("يرجى كتابة نص المنشور قبل النشر.")

elif choice == "أرشيف المنشورات":
  st.subheader("📂 سجل المنشورات السابقة")
  conn = sqlite3.connect(DB_FILE)
  cursor = conn.cursor()
  cursor.execute("SELECT id, content, status FROM posts")
  rows = cursor.fetchall()
  conn.close()

  if rows:
    for row in rows:
      st.info(f"ID: {row[0]} | الحالة: {row[2]}\n\nالنص: {row[1]}")
  else:
    st.write("لا توجد منشورات مسجلة حتى الآن.")
