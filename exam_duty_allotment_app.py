import streamlit as st
import pandas as pd
import pymysql
import random
import io
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# ==========================================================
#                  MYSQL CONFIG  (EDIT THIS)
# ==========================================================

MYSQL_HOST = "192.192.192.100"
MYSQL_USER = "root"
MYSQL_PASSWORD = "your_password"
MYSQL_DB = "VMS2025"


# ==========================================================
#                      DB HELPERS
# ==========================================================

def get_connection():
    return pymysql.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
        cursorclass=pymysql.cursors.DictCursor
    )


def load_user_centres():
    conn = get_connection()
    df = pd.read_sql("SELECT * FROM user_centres", conn)
    conn.close()
    return df


def save_allotment_to_db(df):
    conn = get_connection()
    cur = conn.cursor()

    sql = """
        INSERT INTO allotment_results
        (round_no, rank, user_id, allotted_center, source)
        VALUES (%s, %s, %s, %s, %s)
    """

    for _, row in df.iterrows():
        cur.execute(
            sql,
            (
                int(row["round_no"]),
                int(row["rank"]),
                str(row["user_id"]),
                str(row["allotted_center"]),
                str(row["source"]),
            ),
        )

    conn.commit()
    conn.close()


# ==========================================================
#                   RANK GENERATION
# ==========================================================

def generate_rank(df, seed=2025):
    random.seed(seed)
    df["random_score"] = [random.random() for _ in range(len(df))]

    df = df.sort_values("created_at")
    df["fcfs_rank"] = range(1, len(df) + 1)
    df["fcfs_weight"] = 1 / df["fcfs_rank"]

    df["final_score"] = (
        0.7 * df["fcfs_weight"] +
        0.3 * df["random_score"]
    )

    df = df.sort_values("final_score", ascending=False).reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)
    return df


# ==========================================================
#                   STREAMLIT UI
# ==========================================================

st.set_page_config(page_title="Exam Center Allotment (PyMySQL)", layout="wide")

st.title("🏫 Exam Center Allotment System — PyMySQL Version")
st.markdown("Users → MySQL | Centers → Excel | Ranking → FCFS + Random")


seed = st.sidebar.number_input("Random Seed", value=2025)
round_no = st.sidebar.number_input("Allotment Round", value=1, min_value=1)


# ==========================================================
#           LOAD USERS FROM MYSQL
# ==========================================================

st.subheader("📡 Load Users from MySQL")

if st.button("Load user_centres Table"):
    st.session_state["users"] = load_user_centres()
    st.success("Loaded users from MySQL")

users_df = st.session_state.get("users", load_user_centres())
users_df["created_at"] = pd.to_datetime(users_df["created_at"])

st.dataframe(users_df, use_container_width=True)


# ==========================================================
#          LOAD CENTER CAPACITY FROM EXCEL
# ==========================================================

st.subheader("📥 Upload Center Capacity Excel File")

center_file = st.file_uploader(
    "Upload Excel / CSV (columns: center_code, capacity)",
    type=["xlsx", "csv"]
)

if center_file:
    if center_file.name.endswith(".csv"):
        center_df = pd.read_csv(center_file)
    else:
        center_df = pd.read_excel(center_file)

    st.success("Center file uploaded.")
    st.dataframe(center_df, use_container_width=True)

    # Merge duplicates and sum capacities
    center_df["center_code"] = center_df["center_code"].astype(str)
    center_df["capacity"] = center_df["capacity"].astype(int)

    capacity_dict = (
        center_df.groupby("center_code")["capacity"]
        .sum()
        .to_dict()
    )

else:
    st.warning("Upload center capacity Excel file.")
    st.stop()


remaining_capacity = capacity_dict.copy()


# ==========================================================
#            ADMIN OVERRIDE PANEL
# ==========================================================

st.subheader("🛠 Admin Override Panel")

excluded_users = st.multiselect(
    "Exclude these users:",
    users_df["user_id"].astype(str).tolist()
)

manual_user = st.selectbox(
    "User to manually allot (optional)",
    ["None"] + users_df["user_id"].astype(str).tolist()
)

manual_center = st.selectbox(
    "Center to allot manually",
    ["None"] + list(capacity_dict.keys())
)

manual_override = (
    manual_user != "None" and
    manual_center != "None"
)


# ==========================================================
#               GENERATE RANK
# ==========================================================

st.subheader("🏅 Ranking Results")

ranked_df = generate_rank(users_df.copy(), seed)
st.dataframe(ranked_df, use_container_width=True)


# ==========================================================
#            ALLOTMENT ENGINE
# ==========================================================

st.subheader("🎯 Allotment Results")

allot_list = []

# --------------- MANUAL ALLOTMENT FIRST ------------------

if manual_override:
    row = ranked_df[ranked_df["user_id"].astype(str) == manual_user].iloc[0]

    if remaining_capacity.get(manual_center, 0) > 0:
        remaining_capacity[manual_center] -= 1
        status = manual_center
        source = "MANUAL"
    else:
        status = "NO SEAT"
        source = "MANUAL-FAILED"

    allot_list.append({
        "round_no": round_no,
        "rank": row["rank"],
        "user_id": manual_user,
        "allotted_center": status,
        "source": source,
    })


# --------------- AUTO ALLOTMENT ---------------------------

for _, row in ranked_df.iterrows():
    uid = str(row["user_id"])

    if uid == manual_user:
        continue

    if uid in excluded_users:
        allot_list.append({
            "round_no": round_no,
            "rank": row["rank"],
            "user_id": uid,
            "allotted_center": "EXCLUDED",
            "source": "EXCLUDED",
        })
        continue

    prefs = [row["pref1"], row["pref2"], row["pref3"]]

    allotted = None
    for p in prefs:
        p = str(p)
        if remaining_capacity.get(p, 0) > 0:
            remaining_capacity[p] -= 1
            allotted = p
            break

    if allotted is None:
        allotted = "NO SEAT"

    allot_list.append({
        "round_no": round_no,
        "rank": row["rank"],
        "user_id": uid,
        "allotted_center": allotted,
        "source": "AUTO",
    })


final_df = pd.DataFrame(allot_list)
st.dataframe(final_df, use_container_width=True)


# ==========================================================
#            SAVE RESULTS TO MYSQL
# ==========================================================

if st.button("💾 Save to MySQL"):
    save_allotment_to_db(final_df)
    st.success("Allotment saved into MySQL")


# ==========================================================
#             DUTY SLIP PDF GENERATION
# ==========================================================

st.subheader("🧾 Duty Slip PDF")

if st.button("Generate Duty Slip PDF"):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    for _, row in final_df.iterrows():
        if row["allotted_center"] in ["NO SEAT", "EXCLUDED"]:
            continue

        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, height - 50, "Exam Duty Slip")

        c.setFont("Helvetica", 12)
        c.drawString(50, height - 100, f"Round: {row['round_no']}")
        c.drawString(50, height - 120, f"User ID: {row['user_id']}")
        c.drawString(50, height - 140, f"Center: {row['allotted_center']}")

        c.showPage()

    c.save()
    buf.seek(0)

    st.download_button(
        "Download PDF",
        buf.getvalue(),
        f"duty_slips_round_{round_no}.pdf",
        "application/pdf",
    )
