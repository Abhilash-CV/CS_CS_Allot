import streamlit as st
import pandas as pd
import random
import io

st.set_page_config(page_title="Exam Center Allotment System", layout="wide")

st.title("🏫 Exam Center Allotment System")
st.markdown("Rank = Random + First-Come-First-Serve, with center capacity & PDF duty slips.")

# ------------------ SIDEBAR CONTROLS ------------------ #
st.sidebar.header("Global Settings")

seed = st.sidebar.number_input("Random Seed (for reproducible ranking)", value=2025)
round_no = st.sidebar.number_input("Allotment Round Number", value=1, min_value=1)

st.sidebar.markdown("---")
st.sidebar.markdown("⚙️ Use the controls below & upload files in the main area.")


# ------------------ RANK FUNCTION ------------------ #
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


# ------------------ FILE UPLOADS ------------------ #
st.subheader("📥 Upload Data Files")

col_u1, col_u2 = st.columns(2)

with col_u1:
    user_file = st.file_uploader(
        "Upload Users File (user_id, pref1, pref2, pref3, created_at)",
        type=["csv", "xlsx"],
        key="user_file",
    )

with col_u2:
    center_file = st.file_uploader(
        "Upload Center Capacity File (center_code, capacity)",
        type=["csv", "xlsx"],
        key="center_file",
    )

if user_file and center_file:
    # Read user file
    if user_file.name.endswith(".csv"):
        users_df = pd.read_csv(user_file)
    else:
        users_df = pd.read_excel(user_file)

    # Read centers file
    if center_file.name.endswith(".csv"):
        center_df = pd.read_csv(center_file)
    else:
        center_df = pd.read_excel(center_file)

    st.success("✅ Files uploaded successfully.")

    st.markdown("### 👥 Users Data")
    st.dataframe(users_df, use_container_width=True)

    st.markdown("### 🏫 Centers & Capacities")
    st.dataframe(center_df, use_container_width=True)

    # --------- Validate Columns --------- #
    required_user_cols = ["user_id", "pref1", "pref2", "pref3", "created_at"]
    for col in required_user_cols:
        if col not in users_df.columns:
            st.error(f"❌ Users file missing required column: **{col}**")
            st.stop()

    required_center_cols = ["center_code", "capacity"]
    for col in required_center_cols:
        if col not in center_df.columns:
            st.error(f"❌ Center file missing required column: **{col}**")
            st.stop()

    # Ensure created_at is datetime
    users_df["created_at"] = pd.to_datetime(users_df["created_at"])

    # ------------------ ADMIN OVERRIDES ------------------ #
    st.markdown("## 🛠 Admin Override Panel")

    with st.expander("Exclude specific users from this round", expanded=False):
        all_users = users_df["user_id"].astype(str).tolist()
        excluded_users = st.multiselect(
            "Select users to exclude (no allotment in this round)",
            options=all_users,
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
                options=center_df["center_code"].astype(str).tolist(),
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

    # ------------------ CAPACITY DICT ------------------ #
   # -------- FIX: Correct center capacity handling --------
    center_df["center_code"] = center_df["center_code"].astype(str)
    center_df["capacity"] = center_df["capacity"].astype(int)
    
    # Sum duplicate centers → Correct capacity
    capacity_dict = (
        center_df.groupby("center_code")["capacity"]
        .sum()
        .to_dict()
    )
    
    remaining_capacity = capacity_dict.copy()


    # ------------------ ALLOTMENT LOGIC ------------------ #
    st.markdown("## 🎯 Allotment Processing")

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
            remaining_capacity[center_code] -= 1
            allot_records.append(
                {
                    "round_no": round_no,
                    "rank": row["rank"],
                    "user_id": row["user_id"],
                    "allotted_center": center_code,
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
                    "pref1": row["pref1"],
                    "pref2": row["pref2"],
                    "pref3": row["pref3"],
                    "source": "EXCLUDED",
                }
            )
            continue

        prefs = [row["pref1"], row["pref2"], row["pref3"]]
        allotted_center = None

        for p in prefs:
            if pd.isna(p):
                continue
            p_str = str(p)
            if p_str in remaining_capacity and remaining_capacity[p_str] > 0:
                remaining_capacity[p_str] -= 1
                allotted_center = p_str
                break

        if allotted_center is None:
            allotted_center = "NOT ALLOTTED (NO SEAT)"

        allot_records.append(
            {
                "round_no": round_no,
                "rank": row["rank"],
                "user_id": row["user_id"],
                "allotted_center": allotted_center,
                "pref1": row["pref1"],
                "pref2": row["pref2"],
                "pref3": row["pref3"],
                "source": "AUTO",
            }
        )

    final_allot_df = pd.DataFrame(allot_records)

    st.markdown("### ✅ Final Allotment Result")
    st.dataframe(final_allot_df.sort_values(by=["round_no", "rank"]), use_container_width=True)

    # ------------------ CAPACITY SUMMARY ------------------ #
    st.markdown("## 📊 Capacity Usage Summary")

    used_counts = final_allot_df[final_allot_df["allotted_center"].str.startswith("NOT") == False]
    used_counts = used_counts.groupby("allotted_center").size().reset_index(name="used")

    cap_summary = center_df.copy()
    cap_summary["center_code"] = cap_summary["center_code"].astype(str)
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
    st.markdown("## ⬇ Download Data")

    csv_allot = final_allot_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download Allotment CSV",
        data=csv_allot,
        file_name=f"center_allotment_round_{round_no}.csv",
        mime="text/csv",
    )

    csv_cap = cap_summary.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download Capacity Summary CSV",
        data=csv_cap,
        file_name=f"center_capacity_summary_round_{round_no}.csv",
        mime="text/csv",
    )

    # ------------------ DUTY SLIP PDF ------------------ #
    st.markdown("## 🧾 Generate Duty Slip PDF")

    st.info("PDF generation uses the `reportlab` library. Install it via: `pip install reportlab`")

    generate_pdf = st.button("Generate Duty Slip PDF for All Allotted Users")

    if generate_pdf:
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas

            buffer = io.BytesIO()
            c = canvas.Canvas(buffer, pagesize=A4)
            width, height = A4

            # Only for users with a real center allotment
            for _, row in final_allot_df.iterrows():
                if str(row["allotted_center"]).startswith("NOT") or row["allotted_center"] in [
                    "EXCLUDED_THIS_ROUND",
                    "MANUAL-FAILED",
                ]:
                    continue

                c.setFont("Helvetica-Bold", 16)
                c.drawString(50, height - 60, "Exam Duty Slip")

                c.setFont("Helvetica", 12)
                c.drawString(50, height - 100, f"Round No: {row['round_no']}")
                c.drawString(50, height - 120, f"User ID: {row['user_id']}")
                c.drawString(50, height - 140, f"Allotted Center: {row['allotted_center']}")
                c.drawString(50, height - 170, f"Preference Order: {row['pref1']}, {row['pref2']}, {row['pref3']}")
                c.drawString(50, height - 200, "Please report to the allotted center as per schedule.")

                c.showPage()

            c.save()
            buffer.seek(0)

            st.download_button(
                label="Download Duty Slips PDF",
                data=buffer.getvalue(),
                file_name=f"duty_slips_round_{round_no}.pdf",
                mime="application/pdf",
            )
        except ModuleNotFoundError:
            st.error("❌ Could not import `reportlab`. Please install it: `pip install reportlab`")
        except Exception as e:
            st.error(f"PDF generation failed: {e}")

else:
    st.info("👆 Upload both Users file and Center Capacity file to start.")



