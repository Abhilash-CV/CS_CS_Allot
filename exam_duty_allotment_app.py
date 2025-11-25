import streamlit as st
import pandas as pd
import random
import io

# ----------------------------------------------------------
# APP HEADER
# ----------------------------------------------------------
st.set_page_config(page_title="Exam Duty Allotment System", layout="wide")

st.title("📘 Exam Duty Allotment – Rank Generator")
st.markdown("Automatically handles missing score column & generates ranking.")


# ----------------------------------------------------------
# SIDEBAR SETTINGS
# ----------------------------------------------------------
st.sidebar.header("Settings")

seed = st.sidebar.number_input("Random Seed (for reproducible results)", value=2025)

sort_method = st.sidebar.selectbox(
    "Tie Break Priority",
    [
        "Score → Random → User ID",
        "Score → User ID → Random",
        "Random Only (Ignore Score)",
    ],
)


# ----------------------------------------------------------
# FILE UPLOAD
# ----------------------------------------------------------
st.subheader("Upload CSV or Excel file")
uploaded_file = st.file_uploader("Upload file", type=["csv", "xlsx"])

if uploaded_file:
    # Read file based on extension
    if uploaded_file.name.endswith(".csv"):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)

    st.success("File uploaded successfully!")
    st.dataframe(df, use_container_width=True)

    # ------------------------------------------------------
    # CREATE SCORE IF MISSING
    # ------------------------------------------------------
    if "score" not in df.columns:
        st.warning("⚠️ Column 'score' missing — generating score automatically.")

        # Apply preference-based scoring
        df["score"] = (
            df["pref1"].notna().astype(int) * 3 +
            df["pref2"].notna().astype(int) * 2 +
            df["pref3"].notna().astype(int) * 1
        )

        st.info("✔ Score generated based on preferences (3-2-1 weight).")
        st.dataframe(df, use_container_width=True)

    # ------------------------------------------------------
    # ADD RANDOM NUMBER
    # ------------------------------------------------------
    random.seed(int(seed))
    df["rand"] = [random.random() for _ in range(len(df))]

    # ------------------------------------------------------
    # SORT LOGIC
    # ------------------------------------------------------
    if sort_method == "Score → Random → User ID":
        df = df.sort_values(
            by=["score", "rand", "user_id"],
            ascending=[False, False, True]
        )

    elif sort_method == "Score → User ID → Random":
        df = df.sort_values(
            by=["score", "user_id", "rand"],
            ascending=[False, True, False]
        )

    elif sort_method == "Random Only (Ignore Score)":
        df = df.sort_values(by="rand", ascending=False)

    # ------------------------------------------------------
    # ASSIGN RANK
    # ------------------------------------------------------
    df["rank"] = range(1, len(df) + 1)

    st.subheader("🎯 Final Ranked Output")
    st.dataframe(df, use_container_width=True)

    # ------------------------------------------------------
    # DOWNLOAD OUTPUT
    # ------------------------------------------------------
    st.subheader("⬇ Download Results")

    # CSV Export
    csv_data = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download Ranked CSV",
        data=csv_data,
        file_name="exam_duty_ranked.csv",
        mime="text/csv"
    )

    # Excel Export
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Ranks")
    st.download_button(
        label="Download Excel File",
        data=excel_buffer,
        file_name="exam_duty_ranked.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

st.markdown("---")

