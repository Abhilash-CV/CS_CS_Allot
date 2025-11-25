import streamlit as st
import pandas as pd
import mysql.connector
import random
import io

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


# =======================
#  MYSQL CONFIG
# =======================

MYSQL_HOST = "192.192.192.100"
MYSQL_USER = "Intern"
MYSQL_PASSWORD = "Intern@100"
MYSQL_DB = "VMS2025"


# =======================
#  DB Functions
# =======================

def get_connection():
    return mysql.connector.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB
    )


def load_user_centres():
    conn = get_connection()
    df = pd.read_sql("SELECT * FROM user_centres", conn)
    conn.close()
    return df


def save_allotment_to_db(df):
    conn = get_connection()
    cur = conn.cursor()

    for _, row in df.iterrows():
        sql = """
            INSERT INTO allotment_results
            (round_no, rank, user_id, allotted_center, source)
            VALUES (%s, %s, %s, %s, %s)
        """
        cur.execute(sql, (
            int(row["round_no"]),
            int(row["rank"]),
            str(row["user_id"]),
            str(row["allotted_center"]),
            str(row["source"])
        ))

    conn.commit()
    conn.close()


# =======================
#  RANK GENERATION
# =======================

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


# =======================
# STREAMLIT START
# =======================

st.set_page_config(page_title="Exam Center Allotment", layout="wide")

st.title("🏫 Exam Center Allotment System")
st.markdown("Users → MySQL | Centers → Excel | Rank → Random + FCFS")

seed = st.sidebar.number_input("Random Seed", value=2025)
round_no = st.sidebar.number_input("Allotment Round", value=1, min_value=1)

# -------------------------------
# LOAD USERS FROM MYSQL
# -------------------------------
st.subheader("📡 Users from MySQL")

if st.button("Load user_centres Table"):
    st.session_state["users"] = load_user_centres()
    st.success("Loaded Successfully!")

users_df = st.session_state.get("users", load_user_centres())
st.dataframe(users_df, use_container_width=True)

# Ensure datetime
users_df["created_at"] = pd.to_datetime(users_df["created_at"])


# -------------------------------
# LOAD CENTER CAPACITY FROM EXCEL
# -------------------------------
st.subheader("📥 Upload Center Capacity Excel File")

center_file = st.file_uploader(
    "Upload Excel/CSV with center_code, capacity",
    type=["xlsx", "csv"]
)

if center_file:
    if center_file.name.endswith(".csv"):
        center_df = pd.read_csv(center_file)
    else:
        center_df = pd.read_excel(center_file)

    st.success("Center file uploaded")
    st.dataframe(center_df, use_container_width=True)

    # FIX: Merge duplicates (sum capacities)
    center_df["center_code"] = center_df["center_code"].astype(str)
    center_df["capacity"] = center_df["capacity"].astype(int)

    capacity_dict = (
        center_df.groupby("center_code")["capacity"]
        .sum()
        .to_dict()
    )
else:
    st.warning("Upload center capacity Excel file to continue.")
    st.stop()


# Make a mutable copy for allotment
remaining_capacity = capacity_dict.copy()


# -------------------------------
# ADMIN OVERRIDE
# -------------------------------
st.subheader("🛠 Admin Override Panel")

excluded_users = st.multiselect(
    "Exclude users from this round:",
    users_df["user_id"].astype(str).tolist()
)

manual_user = st.selectbox(
    "User for manual allotment (optional)",
    ["None"] + users_df["user_id"].astype(str).tolist()
)

manual_center = st.selectbox(
    "Center to force assign (optional)",
    ["None"] + list(capacity_dict.keys())
)

manual_override = (
    manual_user != "None" and
    manual_center != "None"
)


# -------------------------------
# GENERATE RANKS
# -------------------------------
st.subheader("🏅 Ranking Users")

ranked_df = generate_rank(users_df.copy(), seed)
st.dataframe(ranked_df, use_container_width=True)


# -------------------------------
# ALLOTMENT ENGINE
# -------------------------------
st.subheader("🎯 Allotment Result")

allot_list = []

# Manual allotment
if manual_override:
    row = ranked_df[ranked_df["user_id"].astype(str) == manual_user].iloc[0]

    if remaining_capacity[manual_center] > 0:
        remaining_capacity[manual_center] -= 1
        result = manual_center
        source = "MANUAL"
    else:
        result = "NO SEAT"
        source = "MANUAL-FAILED"

    allot_list.append({
        "round_no": round_no,
        "rank": row["rank"],
        "user_id": manual_user,
        "allotted_center": result,
        "source": source
    })


# Auto allotment
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
            "source": "EXCLUDED"
        })
        continue

    prefs = [row["pref1"], row["pref2"], row["pref3"]]

    allotted = None
    for p in prefs:
        p = str(p)
        if p in remaining_capacity and remaining_capacity[p] > 0:
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
        "source": "AUTO"
    })

final_df = pd.DataFrame(allot_list)

st.dataframe(final_df, use_container_width=True)


# -------------------------------
# SAVE TO MYSQL
# -------------------------------
if st.button("💾 Save Allotment to MySQL"):
    save_allotment_to_db(final_df)
    st.success("Saved to MySQL successfully!")


# -------------------------------
# DUTY SLIP PDF
# -------------------------------
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
        "Download Duty Slips PDF",
        buf.getvalue(),
        f"duty_slips_round_{round_no}.pdf",
        "application/pdf"
    )
