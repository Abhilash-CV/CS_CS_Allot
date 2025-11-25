import streamlit as st
import pandas as pd
import random

st.set_page_config(page_title="Center Allotment System", layout="wide")

st.title("🏫 Exam Center Allotment System (Preference Based)")
st.markdown("Each user will be allotted to a center based on Pref1 → Pref2 → Pref3")

seed = st.sidebar.number_input("Random Seed", value=2025)

uploaded_file = st.file_uploader("Upload CSV/Excel with user_id, pref1, pref2, pref3", type=["csv", "xlsx"])

if uploaded_file:

    # Load file
    if uploaded_file.name.endswith(".csv"):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)

    st.subheader("Uploaded Data")
    st.dataframe(df)

    # Validate columns
    required_cols = ["user_id", "pref1", "pref2", "pref3"]
    for col in required_cols:
        if col not in df.columns:
            st.error(f"❌ Missing column: {col}")
            st.stop()

    # Add random ranking for tie-breaking
    random.seed(seed)
    df["rand"] = [random.random() for _ in range(len(df))]

    # Sort users so assignment is deterministic
    df = df.sort_values(by=["rand", "user_id"], ascending=[False, True]).reset_index(drop=True)

    # Track center allotments
    allotted_centers = {}
    final_allotment = []

    for _, row in df.iterrows():
        user = row["user_id"]
        prefs = [row["pref1"], row["pref2"], row["pref3"]]

        allotted = None

        for p in prefs:
            if p not in allotted_centers:  # Center free
                allotted = p
                allotted_centers[p] = user
                break

        final_allotment.append({
            "user_id": user,
            "allotted_center": allotted if allotted else "NOT ALLOTTED",
            "pref1": row["pref1"],
            "pref2": row["pref2"],
            "pref3": row["pref3"]
        })

    result_df = pd.DataFrame(final_allotment)

    st.subheader("🎯 Final Allotment Result")
    st.dataframe(result_df, use_container_width=True)

    # Download
    st.download_button(
        label="Download Allotment CSV",
        data=result_df.to_csv(index=False).encode("utf-8"),
        file_name="center_allotment.csv",
        mime="text/csv"
    )

st.markdown("---")

