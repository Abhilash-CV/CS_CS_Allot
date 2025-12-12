import streamlit as st
import pandas as pd
import random
import io
import os
from datetime import datetime

# For email (auto-email duty slips)
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

# ------------------ GLOBAL SETUP ------------------ #
st.set_page_config(page_title="Exam & CC Allotment System", layout="wide")

st.title("🏫 Exam & CC (Lab) Allotment System")
st.markdown(
    "Main Exam Center Allotment = Random + First-Come-First-Serve, "
    "with center capacity & PDF duty slips. CC/Lab allotment is done "
    "for candidates already allotted an exam center."
)

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)


# ------------------ HELPERS ------------------ #
def generate_rank(df: pd.DataFrame, seed: int = 2025) -> pd.DataFrame:
    """Generate rank based on FCFS (created_at) + random."""
    random.seed(seed)

    # Random score for tie-breaking
    df["random_score"] = [random.random() for _ in range(len(df))]

    # Sort by created_at to get FCFS priority
    df = df.sort_values(by="created_at", ascending=True)
    df["fcfs_rank"] = range(1, len(df) + 1)
    df["fcfs_weight"] = 1 / df["fcfs_rank"]  # earlier = bigger weight

    # Combined score: adjust weights if you want
    df["final_score"] = 0.7 * df["fcfs_weight"] + 0.3 * df["random_score"]

    # Final ranking (higher score = higher priority)
    df = df.sort_values(by="final_score", ascending=False).reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)

    return df


def send_email_with_attachment(
    to_email,
    subject,
    body,
    attachment_bytes,
    filename,
    smtp_host,
    smtp_port,
    smtp_user,
    smtp_pass,
):
    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = to_email
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    part = MIMEBase("application", "octet-stream")
    part.set_payload(attachment_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f"attachment; filename={filename}")
    msg.attach(part)

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)


# ------------------ SIDEBAR CONTROLS ------------------ #
st.sidebar.header("Global Settings")

seed = st.sidebar.number_input("Random Seed (for reproducible ranking)", value=2025)
round_no = st.sidebar.number_input("Main Allotment Round Number", value=1, min_value=1)

# Mode switch
mode = st.sidebar.radio(
    "Choose Mode",
    ["Admin - Allotment", "User - View Duty Slip"],
    index=0,
)

st.sidebar.markdown("---")
st.sidebar.markdown("### 📧 Email Settings (Optional)")
enable_email = st.sidebar.checkbox("Enable Auto Email Exam Duty Slips", value=False)
if enable_email:
    smtp_host = st.sidebar.text_input("SMTP Host", value="smtp.gmail.com")
    smtp_port = st.sidebar.number_input("SMTP Port", value=587)
    smtp_user = st.sidebar.text_input("SMTP Username (From Email)")
    smtp_pass = st.sidebar.text_input("SMTP Password", type="password")
else:
    smtp_host = smtp_port = smtp_user = smtp_pass = None

st.sidebar.markdown("---")
st.sidebar.markdown("🕒 Round Management (Main Allotment)")

if st.sidebar.button("Rollback Last Main Round"):
    round_files = []
    for fname in os.listdir(DATA_DIR):
        if fname.startswith("allotments_round_") and fname.endswith(".csv"):
            try:
                rno = int(fname.replace("allotments_round_", "").replace(".csv", ""))
                round_files.append((rno, fname))
            except ValueError:
                continue
    if not round_files:
        st.sidebar.warning("No main round data found to rollback.")
    else:
        max_round, max_file = max(round_files, key=lambda x: x[0])
        os.remove(os.path.join(DATA_DIR, max_file))
        st.sidebar.success(
            f"Rolled back main round {max_round}. Please reload allotment for next round."
        )

        remaining = [rf for rf in round_files if rf[0] != max_round]
        if remaining:
            new_max_round, new_file = max(remaining, key=lambda x: x[0])
            prev_df = pd.read_csv(os.path.join(DATA_DIR, new_file))
            latest_file = os.path.join(DATA_DIR, "allotments_latest.csv")
            prev_df.to_csv(latest_file, index=False)
        else:
            latest_file = os.path.join(DATA_DIR, "allotments_latest.csv")
            if os.path.exists(latest_file):
                os.remove(latest_file)

st.sidebar.markdown("---")
st.sidebar.markdown("⚙️ Use the controls below & upload files in the main area.")


# =========================================================
#                    ADMIN MODE
# =========================================================
if mode == "Admin - Allotment":

    # ------------------ AUTO-LOCK USERS FROM PREVIOUS ROUNDS ------------------ #
    locked_users = set()
    for fname in os.listdir(DATA_DIR):
        if fname.startswith("allotments_round_") and fname.endswith(".csv"):
            try:
                rno = int(fname.replace("allotments_round_", "").replace(".csv", ""))
            except ValueError:
                continue
            if rno >= round_no:
                continue
            prev_df = pd.read_csv(os.path.join(DATA_DIR, fname))
            valid_prev = prev_df[
                prev_df["allotted_center"].astype(str).str.startswith("NOT") == False
            ]
            valid_prev = valid_prev[
                ~valid_prev["allotted_center"].isin(
                    ["EXCLUDED_THIS_ROUND", "MANUAL-FAILED"]
                )
            ]
            locked_users.update(valid_prev["user_id"].astype(str).tolist())

    st.sidebar.markdown(
        f"🔒 Auto-locked users from previous main rounds: {len(locked_users)}"
    )

    # ------------------ FILE UPLOADS ------------------ #
    st.subheader("📥 Upload Data Files (Main Exam Allotment)")

    col_u1, col_u2 = st.columns(2)

    with col_u1:
        user_file = st.file_uploader(
            "Upload Users File (user_id, pref1, pref2, pref3, created_at, [email])",
            type=["csv", "xlsx"],
            key="user_file",
        )

    with col_u2:
        center_file = st.file_uploader(
            "Upload Exam Center Capacity File (center_code, venueno, capacity)",
            type=["csv", "xlsx"],
            key="center_file",
        )

    if user_file and center_file:
        # Read user file
        if user_file.name.endswith(".csv"):
            users_df = pd.read_csv(user_file)
        else:
            users_df = pd.read_excel(user_file)

        # Read centers file (with venueno rows)
        if center_file.name.endswith(".csv"):
            center_df = pd.read_csv(center_file)
        else:
            center_df = pd.read_excel(center_file)

        st.success("✅ Files uploaded successfully.")

        st.markdown("### 👥 Users Data")
        st.dataframe(users_df, use_container_width=True)

        st.markdown("### 🏫 Exam Centers & Venues (uploaded)")
        st.dataframe(center_df, use_container_width=True)

        # --------- Validate Columns --------- #
        required_user_cols = ["user_id", "pref1", "pref2", "pref3", "created_at"]
        for col in required_user_cols:
            if col not in users_df.columns:
                st.error(f"❌ Users file missing required column: **{col}**")
                st.stop()

        required_center_cols = ["center_code", "venueno", "capacity"]
        for col in required_center_cols:
            if col not in center_df.columns:
                st.error(f"❌ Center file missing required column: **{col}**")
                st.stop()

        # Ensure created_at is datetime
        users_df["created_at"] = pd.to_datetime(users_df["created_at"])

        # Normalize center_df types
        center_df["center_code"] = center_df["center_code"].astype(str)
        center_df["venueno"] = center_df["venueno"].astype(str)
        center_df["capacity"] = center_df["capacity"].astype(int)

        # ------------------ ADMIN OVERRIDES ------------------ #
        st.markdown("## 🛠 Admin Override Panel (Main)")

        with st.expander("Exclude specific users from this round", expanded=False):
            all_users = users_df["user_id"].astype(str).tolist()
            default_excluded = sorted(locked_users)
            excluded_users = st.multiselect(
                "Select users to exclude (auto-includes already allotted users)",
                options=all_users,
                default=default_excluded,
            )

        with st.expander("Manual fixed allotments (force a user → center)", expanded=False):
            fixed_assignments = {}

            enable_manual = st.checkbox("Enable one manual override", value=False)
            if enable_manual:
                override_user = st.selectbox(
                    "Choose user to fix allotment",
                    options=users_df["user_id"].astype(str).tolist(),
                )
                override_center = st.selectbox(
                    "Choose center to allot manually",
                    options=sorted(center_df["center_code"].unique().astype(str).tolist()),
                )
                st.info(
                    "This user will be allotted to this center **before** automatic allotment, "
                    "if capacity is available."
                )
                if st.button("Apply manual override"):
                    fixed_assignments[override_user] = override_center
                    st.success(
                        f"Manual override recorded: User {override_user} → Center {override_center}"
                    )

        # ------------------ RANK GENERATION ------------------ #
        st.markdown("## 🏅 Ranking (Random + FCFS)")

        ranked_users = generate_rank(users_df.copy(), seed=seed)
        st.dataframe(ranked_users, use_container_width=True)

        # ------------------ CAPACITY DICT & VENUE MAP ------------------ #
        # Sum capacity per center (total seats available at center level)
        capacity_dict = center_df.groupby("center_code")["capacity"].sum().to_dict()

        # Build venue slots per center: center_code -> list of venueno (each repeated by its capacity)
        venue_map = {}
        for _, r in center_df.iterrows():
            center = str(r["center_code"])
            venue = str(r["venueno"])
            cap = int(r["capacity"])
            venue_map.setdefault(center, [])
            for _ in range(cap):
                venue_map[center].append(venue)

        # remaining_capacity is center-level seats left
        remaining_capacity = capacity_dict.copy()

        # ------------------ ALLOTMENT PROCESSING ------------------ #
        st.markdown("## 🎯 Main Exam Allotment Processing")

        allot_records = []

        # 1) Apply manual fixed assignments first
        for user_str, center_code in fixed_assignments.items():
            # Find the user row
            row = ranked_users[ranked_users["user_id"].astype(str) == user_str]
            if row.empty:
                continue  # user not found

            row = row.iloc[0]

            # Check capacity
            if center_code in remaining_capacity and remaining_capacity[center_code] > 0:
                # Allocate center-level seat
                remaining_capacity[center_code] -= 1

                # Assign venue if available
                venue_no = None
                if center_code in venue_map and venue_map[center_code]:
                    venue_no = venue_map[center_code].pop(0)
                else:
                    # no venue available even if center capacity indicated (edge case)
                    venue_no = "NO_VENUE"

                allot_records.append(
                    {
                        "round_no": round_no,
                        "rank": row["rank"],
                        "user_id": row["user_id"],
                        "allotted_center": center_code,
                        "venueno": venue_no,
                        "pref1": row["pref1"],
                        "pref2": row["pref2"],
                        "pref3": row["pref3"],
                        "source": "MANUAL",
                    }
                )
            else:
                allot_records.append(
                    {
                        "round_no": round_no,
                        "rank": row["rank"],
                        "user_id": row["user_id"],
                        "allotted_center": "NOT ALLOTTED (NO CAPACITY)",
                        "venueno": "",
                        "pref1": row["pref1"],
                        "pref2": row["pref2"],
                        "pref3": row["pref3"],
                        "source": "MANUAL-FAILED",
                    }
                )

        # Users already handled manually or excluded should not be auto-processed
        manually_handled_users = set(fixed_assignments.keys())
        excluded_users_set = set(excluded_users)

        # 2) Automatic allotment by rank for remaining users
        for _, row in ranked_users.iterrows():
            u_str = str(row["user_id"])
            if u_str in manually_handled_users:
                continue
            if u_str in excluded_users_set:
                allot_records.append(
                    {
                        "round_no": round_no,
                        "rank": row["rank"],
                        "user_id": row["user_id"],
                        "allotted_center": "EXCLUDED_THIS_ROUND",
                        "venueno": "",
                        "pref1": row["pref1"],
                        "pref2": row["pref2"],
                        "pref3": row["pref3"],
                        "source": "EXCLUDED",
                    }
                )
                continue

            prefs = [row["pref1"], row["pref2"], row["pref3"]]
            allotted_center = None
            assigned_venue = ""

            for p in prefs:
                if pd.isna(p):
                    continue
                p_str = str(p)
                if p_str in remaining_capacity and remaining_capacity[p_str] > 0:
                    # allocate at center level
                    remaining_capacity[p_str] -= 1
                    allotted_center = p_str

                    # assign a venue from the venue_map
                    if p_str in venue_map and venue_map[p_str]:
                        assigned_venue = venue_map[p_str].pop(0)
                    else:
                        assigned_venue = "NO_VENUE"
                    break

            if allotted_center is None:
                allot_records.append(
                    {
                        "round_no": round_no,
                        "rank": row["rank"],
                        "user_id": row["user_id"],
                        "allotted_center": "NOT ALLOTTED (NO SEAT)",
                        "venueno": "",
                        "pref1": row["pref1"],
                        "pref2": row["pref2"],
                        "pref3": row["pref3"],
                        "source": "AUTO",
                    }
                )
            else:
                allot_records.append(
                    {
                        "round_no": round_no,
                        "rank": row["rank"],
                        "user_id": row["user_id"],
                        "allotted_center": allotted_center,
                        "venueno": assigned_venue,
                        "pref1": row["pref1"],
                        "pref2": row["pref2"],
                        "pref3": row["pref3"],
                        "source": "AUTO",
                    }
                )

        final_allot_df = pd.DataFrame(allot_records)

        st.markdown("### ✅ Final Main Allotment Result")
        st.dataframe(
            final_allot_df.sort_values(by=["round_no", "rank"]),
            use_container_width=True,
        )

        # ---------- SAVE ALLOTMENT TO DISK / SESSION ---------- #
        round_file = os.path.join(DATA_DIR, f"allotments_round_{round_no}.csv")
        final_allot_df.to_csv(round_file, index=False)

        latest_file = os.path.join(DATA_DIR, "allotments_latest.csv")
        final_allot_df.to_csv(latest_file, index=False)

        st.session_state["final_allot_df"] = final_allot_df

        # ------------------ 📈 LIVE DASHBOARD ------------------ #
        st.markdown("## 📈 Live Dashboard (Main)")

        total_users = len(final_allot_df)
        total_allotted = (
            final_allot_df["allotted_center"]
            .astype(str)
            .apply(
                lambda x: not x.startswith("NOT")
                and x not in ["EXCLUDED_THIS_ROUND", "MANUAL-FAILED"]
            )
            .sum()
        )
        total_excluded = (final_allot_df["source"] == "EXCLUDED").sum()

        col_kpi1, col_kpi2, col_kpi3 = st.columns(3)
        with col_kpi1:
            st.metric("Total Users in Round", total_users)
        with col_kpi2:
            st.metric("Total Allotted (Main)", total_allotted)
        with col_kpi3:
            st.metric("Excluded This Round", total_excluded)

        st.markdown("#### Center-wise Allotment Count")
        center_usage = (
            final_allot_df[
                final_allot_df["allotted_center"].astype(str).str.startswith("NOT")
                == False
            ]
            .groupby("allotted_center")
            .size()
            .reset_index(name="count")
        )

        if not center_usage.empty:
            st.bar_chart(center_usage.set_index("allotted_center"))

        st.markdown("#### Allotment Outcome Distribution")
        outcome_dist = (
            final_allot_df["allotted_center"]
            .value_counts()
            .reset_index()
        )
        outcome_dist.columns = ["allotted_center", "count"]
        st.dataframe(outcome_dist, use_container_width=True)

        # ------------------ CAPACITY SUMMARY (aggregate per center) ------------------ #
        st.markdown("## 📊 Capacity Usage Summary (Main)")

        used_counts = final_allot_df[
            final_allot_df["allotted_center"].astype(str).str.startswith("NOT") == False
        ]
        used_counts = (
            used_counts.groupby("allotted_center").size().reset_index(name="used")
        )

        cap_summary = (
            center_df.groupby("center_code")["capacity"]
            .sum()
            .reset_index()
            .rename(columns={"center_code": "center_code", "capacity": "capacity"})
        )

        cap_summary = cap_summary.merge(
            used_counts,
            how="left",
            left_on="center_code",
            right_on="allotted_center",
        ).drop(columns=["allotted_center"])

        cap_summary["used"] = cap_summary["used"].fillna(0).astype(int)
        cap_summary["remaining"] = cap_summary["capacity"] - cap_summary["used"]

        st.dataframe(cap_summary, use_container_width=True)

        # ------------------ DOWNLOAD BUTTONS ------------------ #
        st.markdown("## ⬇ Download Main Allotment Data")

        csv_allot = final_allot_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download Main Allotment CSV",
            data=csv_allot,
            file_name=f"center_allotment_round_{round_no}.csv",
            mime="text/csv",
        )

        csv_cap = cap_summary.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download Main Capacity Summary CSV",
            data=csv_cap,
            file_name=f"center_capacity_summary_round_{round_no}.csv",
            mime="text/csv",
        )

        # ------------------------------------------------------
        #              💻 CC / LAB (VENUE) ALLOTMENT
        # ------------------------------------------------------
        st.markdown("## 💻 CC / Lab Allotment")

        st.info(
            "CC allotment uses: (1) this round's final exam allotment, "
            "(2) the same users file, and (3) a lab_venue file with columns "
            "`collegecode, venueno, tempvno`."
        )

        lab_file = st.file_uploader(
            "Upload Lab Venue File (collegecode, venueno, tempvno)",
            type=["csv", "xlsx"],
            key="lab_file",
        )

        if lab_file is not None:
            # Read lab venue file
            if lab_file.name.endswith(".csv"):
                lab_df = pd.read_csv(lab_file)
            else:
                lab_df = pd.read_excel(lab_file)

            st.markdown("### 🧪 Lab / Venue Data (CC)")
            st.dataframe(lab_df, use_container_width=True)

            # Validate lab_venue columns
            required_lab_cols = ["collegecode", "venueno", "tempvno"]
            for col in required_lab_cols:
                if col not in lab_df.columns:
                    st.error(f"❌ Lab venue file missing required column: **{col}**")
                    st.stop()

            # Normalize types
            lab_df["collegecode"] = lab_df["collegecode"].astype(str)
            lab_df["venueno"] = lab_df["venueno"].astype(str)
            lab_df["tempvno"] = lab_df["tempvno"].astype(int)

            # CC round number (separate from main round)
            cc_round_no = st.number_input(
                "CC Allotment Round Number",
                min_value=1,
                value=1,
                key="cc_round_no",
            )

            # Optional: email CC slips too
            cc_email_enabled = st.checkbox(
                "Send CC duty slips via email (use same SMTP settings)", value=False
            )

            # Build remaining capacity per (collegecode, venueno)
            cc_capacity = {}
            for _, r in lab_df.iterrows():
                key = (r["collegecode"], r["venueno"])
                cc_capacity[key] = cc_capacity.get(key, 0) + int(r["tempvno"])

            cc_remaining = cc_capacity.copy()

            # Eligible users = those with a valid exam center allotment
            valid_exam = final_allot_df[
                final_allot_df["allotted_center"].astype(str).str.startswith("NOT")
                == False
            ]
            valid_exam = valid_exam[
                ~valid_exam["allotted_center"].isin(
                    ["EXCLUDED_THIS_ROUND", "MANUAL-FAILED"]
                )
            ]

            if valid_exam.empty:
                st.warning("No candidates with valid exam center allotment for CC.")
            else:
                # Sort by exam rank (same priority order)
                valid_exam = valid_exam.sort_values(by="rank")

                # Map user_id → email (if exists)
                email_map_cc = {}
                if cc_email_enabled and "email" in users_df.columns:
                    tmp_users_cc = users_df.copy()
                    tmp_users_cc["user_id"] = tmp_users_cc["user_id"].astype(str)
                    email_map_cc = dict(
                        zip(tmp_users_cc["user_id"], tmp_users_cc["email"])
                    )
                elif cc_email_enabled and "email" not in users_df.columns:
                    st.warning(
                        "Users file has no 'email' column; CC emails cannot be sent."
                    )
                    cc_email_enabled = False

                # Process CC allotment
                cc_allot_records = []

                for _, row in valid_exam.iterrows():
                    uid = str(row["user_id"])
                    college = str(row["allotted_center"])  # must match collegecode

                    # Find any venue under this college with remaining capacity
                    possible_venues = [
                        key
                        for key, cap in cc_remaining.items()
                        if key[0] == college and cap > 0
                    ]

                    if possible_venues:
                        # Simple: choose smallest venueno for stability
                        chosen_key = sorted(possible_venues, key=lambda x: x[1])[0]
                        cc_remaining[chosen_key] -= 1
                        chosen_venue = chosen_key[1]
                    else:
                        chosen_venue = "NO_LAB_SEAT"

                    cc_allot_records.append(
                        {
                            "cc_round_no": cc_round_no,
                            "round_no": row["round_no"],
                            "rank": row["rank"],
                            "user_id": row["user_id"],
                            "exam_center": row["allotted_center"],
                            "cc_venueno": chosen_venue,
                            "pref1": row["pref1"],
                            "pref2": row["pref2"],
                            "pref3": row["pref3"],
                            "source": "CC-AUTO",
                        }
                    )

                cc_allot_df = pd.DataFrame(cc_allot_records)

                st.markdown("### ✅ CC / Lab Allotment Result")
                st.dataframe(
                    cc_allot_df.sort_values(by=["cc_round_no", "rank"]),
                    use_container_width=True,
                )

                # Save CC allotment to disk
                cc_round_file = os.path.join(
                    DATA_DIR, f"cc_allotments_round_{cc_round_no}.csv"
                )
                cc_allot_df.to_csv(cc_round_file, index=False)

                cc_latest_file = os.path.join(DATA_DIR, "cc_allotments_latest.csv")
                cc_allot_df.to_csv(cc_latest_file, index=False)

                # CC capacity summary
                st.markdown("### 📊 CC Capacity Usage Summary")

                used_cc = cc_allot_df[
                    cc_allot_df["cc_venueno"].astype(str) != "NO_LAB_SEAT"
                ]
                used_cc_counts = (
                    used_cc.groupby(["exam_center", "cc_venueno"])
                    .size()
                    .reset_index(name="used")
                )

                lab_df_for_merge = lab_df.rename(
                    columns={
                        "collegecode": "exam_center",
                        "venueno": "cc_venueno",
                        "tempvno": "capacity",
                    }
                )

                cc_cap_summary = lab_df_for_merge.merge(
                    used_cc_counts,
                    how="left",
                    on=["exam_center", "cc_venueno"],
                )
                cc_cap_summary["used"] = cc_cap_summary["used"].fillna(0).astype(int)
                cc_cap_summary["remaining"] = (
                    cc_cap_summary["capacity"] - cc_cap_summary["used"]
                )

                st.dataframe(cc_cap_summary, use_container_width=True)

                # Download CC CSV
                st.markdown("### ⬇ Download CC Allotment Data")

                csv_cc_allot = cc_allot_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="Download CC Allotment CSV",
                    data=csv_cc_allot,
                    file_name=f"cc_allotment_round_{cc_round_no}.csv",
                    mime="text/csv",
                )

                csv_cc_cap = cc_cap_summary.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="Download CC Capacity Summary CSV",
                    data=csv_cc_cap,
                    file_name=f"cc_capacity_summary_round_{cc_round_no}.csv",
                    mime="text/csv",
                )

                # ---------- CC DUTY SLIP PDF + EMAIL (OPTIONAL) ---------- #
                st.markdown("### 🧾 Generate CC Duty Slip PDF")

                cc_generate_pdf = st.button(
                    "Generate CC Duty Slip PDF for All CC-Allotted Users"
                )

                if cc_generate_pdf:
                    try:
                        from reportlab.lib.pagesizes import A4
                        from reportlab.pdfgen import canvas

                        # Combined CC PDF for admin
                        cc_combined_buffer = io.BytesIO()
                        cc_canvas = canvas.Canvas(cc_combined_buffer, pagesize=A4)
                        width, height = A4

                        for _, row in cc_allot_df.iterrows():
                            if str(row["cc_venueno"]) == "NO_LAB_SEAT":
                                continue

                            # Add page in combined CC PDF
                            cc_canvas.setFont("Helvetica-Bold", 16)
                            cc_canvas.drawString(50, height - 60, "CC / Lab Duty Slip")

                            cc_canvas.setFont("Helvetica", 12)
                            cc_canvas.drawString(
                                50, height - 100, f"CC Round No: {row['cc_round_no']}"
                            )
                            cc_canvas.drawString(
                                50,
                                height - 120,
                                f"User ID: {row['user_id']}",
                            )
                            cc_canvas.drawString(
                                50,
                                height - 140,
                                f"Exam Center (College): {row['exam_center']}",
                            )
                            cc_canvas.drawString(
                                50,
                                height - 160,
                                f"Lab / Venue No: {row['cc_venueno']}",
                            )
                            cc_canvas.drawString(
                                50,
                                height - 190,
                                f"Preference Order: {row['pref1']}, {row['pref2']}, {row['pref3']}",
                            )
                            cc_canvas.drawString(
                                50,
                                height - 220,
                                "Please report to the allotted lab as per schedule.",
                            )
                            cc_canvas.showPage()

                            # Individual CC email
                            if cc_email_enabled and smtp_host and smtp_user and smtp_pass:
                                uid = str(row["user_id"])
                                user_email = email_map_cc.get(uid)
                                if user_email:
                                    try:
                                        indiv_buffer = io.BytesIO()
                                        c2 = canvas.Canvas(
                                            indiv_buffer, pagesize=A4
                                        )
                                        c2.setFont("Helvetica-Bold", 16)
                                        c2.drawString(
                                            50, height - 60, "CC / Lab Duty Slip"
                                        )
                                        c2.setFont("Helvetica", 12)
                                        c2.drawString(
                                            50,
                                            height - 100,
                                            f"CC Round No: {row['cc_round_no']}",
                                        )
                                        c2.drawString(
                                            50,
                                            height - 120,
                                            f"User ID: {row['user_id']}",
                                        )
                                        c2.drawString(
                                            50,
                                            height - 140,
                                            f"Exam Center (College): {row['exam_center']}",
                                        )
                                        c2.drawString(
                                            50,
                                            height - 160,
                                            f"Lab / Venue No: {row['cc_venueno']}",
                                        )
                                        c2.drawString(
                                            50,
                                            height - 190,
                                            f"Preference Order: {row['pref1']}, {row['pref2']}, {row['pref3']}",
                                        )
                                        c2.drawString(
                                            50,
                                            height - 220,
                                            "Please report to the allotted lab as per schedule.",
                                        )
                                        c2.showPage()
                                        c2.save()
                                        indiv_buffer.seek(0)

                                        subject = "CC / Lab Duty Slip"
                                        body = (
                                            "Dear Candidate,\n\n"
                                            "Please find your CC / Lab duty slip attached.\n\n"
                                            "Regards,\nExam Cell"
                                        )

                                        send_email_with_attachment(
                                            user_email,
                                            subject,
                                            body,
                                            indiv_buffer.getvalue(),
                                            f"cc_duty_slip_{uid}.pdf",
                                            smtp_host,
                                            smtp_port,
                                            smtp_user,
                                            smtp_pass,
                                        )
                                    except Exception as ee:
                                        st.warning(
                                            f"Failed to send CC email to {uid}: {ee}"
                                        )

                        cc_canvas.save()
                        cc_combined_buffer.seek(0)

                        st.download_button(
                            label="Download CC Duty Slips PDF (Admin)",
                            data=cc_combined_buffer.getvalue(),
                            file_name=f"cc_duty_slips_round_{cc_round_no}.pdf",
                            mime="application/pdf",
                        )

                    except Exception as e:
                        st.error(f"CC PDF generation or email failed: {e}")

        # ------------------ DUTY SLIP PDF + AUTO-EMAIL (MAIN) ------------------ #
        st.markdown("## 🧾 Generate Main Exam Duty Slip PDF")

        st.info(
            "Main PDF generation uses the `reportlab` library. "
            "Install it via: `pip install reportlab`"
        )

        generate_pdf = st.button("Generate Exam Duty Slip PDF for All Allotted Users")

        if generate_pdf:
            try:
                from reportlab.lib.pagesizes import A4
                from reportlab.pdfgen import canvas

                # Email column check if needed
                if enable_email and "email" not in users_df.columns:
                    st.error("Users file does not have an 'email' column. Cannot send emails.")
                    enable_email = False

                # Map user_id -> email
                email_map = {}
                if enable_email:
                    tmp_users = users_df.copy()
                    tmp_users["user_id"] = tmp_users["user_id"].astype(str)
                    email_map = dict(zip(tmp_users["user_id"], tmp_users["email"]))

                # -------------- Combined PDF (download for admin) -------------- #
                combined_buffer = io.BytesIO()
                combined_canvas = canvas.Canvas(combined_buffer, pagesize=A4)
                width, height = A4

                for _, row in final_allot_df.iterrows():
                    # Skip non-allotted users
                    if (
                        str(row["allotted_center"]).startswith("NOT")
                        or row["allotted_center"]
                        in ["EXCLUDED_THIS_ROUND", "MANUAL-FAILED"]
                    ):
                        continue

                    # Draw page for combined PDF
                    combined_canvas.setFont("Helvetica-Bold", 16)
                    combined_canvas.drawString(50, height - 60, "Exam Duty Slip")
                    combined_canvas.setFont("Helvetica", 12)
                    combined_canvas.drawString(
                        50, height - 100, f"Round No: {row['round_no']}"
                    )
                    combined_canvas.drawString(
                        50, height - 120, f"User ID: {row['user_id']}"
                    )
                    combined_canvas.drawString(
                        50,
                        height - 140,
                        f"Allotted Center: {row['allotted_center']}",
                    )
                    # Venue display
                    combined_canvas.drawString(
                        50,
                        height - 160,
                        f"Venue No: {row.get('venueno', '')}",
                    )
                    combined_canvas.drawString(
                        50,
                        height - 190,
                        f"Preference Order: {row['pref1']}, {row['pref2']}, {row['pref3']}",
                    )
                    combined_canvas.drawString(
                        50,
                        height - 220,
                        "Please report to the allotted center as per schedule.",
                    )
                    combined_canvas.showPage()

                    # -------------- Individual PDF (email only) -------------- #
                    if enable_email and smtp_host and smtp_user and smtp_pass:
                        uid = str(row["user_id"])
                        user_email = email_map.get(uid)

                        if user_email:
                            try:
                                indiv_buffer = io.BytesIO()
                                c2 = canvas.Canvas(indiv_buffer, pagesize=A4)

                                c2.setFont("Helvetica-Bold", 16)
                                c2.drawString(50, height - 60, "Exam Duty Slip")
                                c2.setFont("Helvetica", 12)
                                c2.drawString(
                                    50,
                                    height - 100,
                                    f"Round No: {row['round_no']}",
                                )
                                c2.drawString(
                                    50,
                                    height - 120,
                                    f"User ID: {row['user_id']}",
                                )
                                c2.drawString(
                                    50,
                                    height - 140,
                                    f"Allotted Center: {row['allotted_center']}",
                                )
                                c2.drawString(
                                    50,
                                    height - 160,
                                    f"Venue No: {row.get('venueno', '')}",
                                )
                                c2.drawString(
                                    50,
                                    height - 190,
                                    f"Preference Order: {row['pref1']}, {row['pref2']}, {row['pref3']}",
                                )
                                c2.drawString(
                                    50,
                                    height - 220,
                                    "Please report to the allotted center as per schedule.",
                                )
                                c2.showPage()
                                c2.save()
                                indiv_buffer.seek(0)

                                subject = "Exam Duty Slip"
                                body = (
                                    "Dear Candidate,\n\n"
                                    "Please find your exam duty slip attached.\n\n"
                                    "Regards,\nExam Cell"
                                )

                                send_email_with_attachment(
                                    user_email,
                                    subject,
                                    body,
                                    indiv_buffer.getvalue(),
                                    f"duty_slip_{uid}.pdf",
                                    smtp_host,
                                    smtp_port,
                                    smtp_user,
                                    smtp_pass,
                                )
                            except Exception as ee:
                                st.warning(f"Failed to send email to {uid}: {ee}")

                combined_canvas.save()
                combined_buffer.seek(0)

                st.download_button(
                    label="Download Exam Duty Slips PDF (Admin)",
                    data=combined_buffer.getvalue(),
                    file_name=f"duty_slips_round_{round_no}.pdf",
                    mime="application/pdf",
                )

            except Exception as e:
                st.error(f"PDF generation or email failed: {e}")

    else:
        st.info("👆 Upload both Users file and Exam Center Capacity file to start.")


# =========================================================
#                    USER MODE
# =========================================================
if mode == "User - View Duty Slip":
    st.subheader("👤 User Duty Slip Portal")

    st.info(
        "Enter your User ID to view your Main Exam duty slip and "
        "CC/Lab duty slip (if allotted)."
    )

    user_id_input = st.text_input("User ID", "")

    # ------------------ MAIN EXAM SLIP ------------------ #
    st.markdown("### 🎫 Main Exam Duty Slip")

    latest_file = os.path.join(DATA_DIR, "allotments_latest.csv")
    exam_row = None
    if not os.path.exists(latest_file):
        st.warning("Main exam allotment not yet published.")
    else:
        latest_df = pd.read_csv(latest_file)

        if st.button("Fetch My Allotment (Main + CC)"):
            if not user_id_input:
                st.error("Please enter your User ID.")
            else:
                rows = latest_df[latest_df["user_id"].astype(str) == user_id_input]
                if rows.empty:
                    st.error("No main exam record found for this User ID.")
                else:
                    exam_row = rows.iloc[0]
                    st.success(f"Main exam allotment found for User ID: {user_id_input}")
                    st.write(exam_row)

                    if str(exam_row["allotted_center"]).startswith("NOT") or exam_row[
                        "allotted_center"
                    ] in ["EXCLUDED_THIS_ROUND", "MANUAL-FAILED"]:
                        st.warning(
                            "You have not been allotted any main exam center in this round."
                        )
                    else:
                        try:
                            from reportlab.lib.pagesizes import A4
                            from reportlab.pdfgen import canvas

                            buffer = io.BytesIO()
                            c = canvas.Canvas(buffer, pagesize=A4)
                            width, height = A4

                            c.setFont("Helvetica-Bold", 16)
                            c.drawString(50, height - 60, "Exam Duty Slip")

                            c.setFont("Helvetica", 12)
                            c.drawString(
                                50,
                                height - 100,
                                f"Round No: {exam_row['round_no']}",
                            )
                            c.drawString(
                                50,
                                height - 120,
                                f"User ID: {exam_row['user_id']}",
                            )
                            c.drawString(
                                50,
                                height - 140,
                                f"Allotted Center: {exam_row['allotted_center']}",
                            )
                            # Venue display in user PDF
                            if "venueno" in exam_row:
                                c.drawString(
                                    50,
                                    height - 160,
                                    f"Venue No: {exam_row.get('venueno', '')}",
                                )

                            c.drawString(
                                50,
                                height - 190,
                                f"Preference Order: {exam_row['pref1']}, {exam_row['pref2']}, {exam_row['pref3']}",
                            )
                            c.drawString(
                                50,
                                height - 220,
                                "Please report to the allotted center as per schedule.",
                            )

                            c.showPage()
                            c.save()
                            buffer.seek(0)

                            st.download_button(
                                label="Download My Exam Duty Slip (PDF)",
                                data=buffer.getvalue(),
                                file_name=f"duty_slip_{user_id_input}.pdf",
                                mime="application/pdf",
                            )
                        except Exception as e:
                            st.error(f"Main exam PDF generation failed: {e}")

                # ------------------ CC / LAB SLIP ------------------ #
                st.markdown("### 💻 CC / Lab Duty Slip")

                cc_latest_file = os.path.join(DATA_DIR, "cc_allotments_latest.csv")
                if not os.path.exists(cc_latest_file):
                    st.warning("CC / Lab allotment not yet published.")
                else:
                    cc_df = pd.read_csv(cc_latest_file)
                    cc_rows = cc_df[cc_df["user_id"].astype(str) == user_id_input]
                    if cc_rows.empty:
                        st.warning("No CC / Lab record found for this User ID.")
                    else:
                        cc_row = cc_rows.iloc[0]
                        st.success(
                            f"CC / Lab allotment found for User ID: {user_id_input}"
                        )
                        st.write(cc_row)

                        if str(cc_row["cc_venueno"]) == "NO_LAB_SEAT":
                            st.warning(
                                "You do not have a CC / Lab seat in the current CC round."
                            )
                        else:
                            try:
                                from reportlab.lib.pagesizes import A4
                                from reportlab.pdfgen import canvas

                                buffer_cc = io.BytesIO()
                                c3 = canvas.Canvas(buffer_cc, pagesize=A4)
                                width, height = A4

                                c3.setFont("Helvetica-Bold", 16)
                                c3.drawString(50, height - 60, "CC / Lab Duty Slip")

                                c3.setFont("Helvetica", 12)
                                c3.drawString(
                                    50,
                                    height - 100,
                                    f"CC Round No: {cc_row['cc_round_no']}",
                                )
                                c3.drawString(
                                    50,
                                    height - 120,
                                    f"User ID: {cc_row['user_id']}",
                                )
                                c3.drawString(
                                    50,
                                    height - 140,
                                    f"Exam Center (College): {cc_row['exam_center']}",
                                )
                                c3.drawString(
                                    50,
                                    height - 160,
                                    f"Lab / Venue No: {cc_row['cc_venueno']}",
                                )
                                c3.drawString(
                                    50,
                                    height - 190,
                                    f"Preference Order: {cc_row['pref1']}, {cc_row['pref2']}, {cc_row['pref3']}",
                                )
                                c3.drawString(
                                    50,
                                    height - 220,
                                    "Please report to the allotted lab as per schedule.",
                                )

                                c3.showPage()
                                c3.save()
                                buffer_cc.seek(0)

                                st.download_button(
                                    label="Download My CC / Lab Duty Slip (PDF)",
                                    data=buffer_cc.getvalue(),
                                    file_name=f"cc_duty_slip_{user_id_input}.pdf",
                                    mime="application/pdf",
                                )
                            except Exception as e:
                                st.error(f"CC / Lab PDF generation failed: {e}")
