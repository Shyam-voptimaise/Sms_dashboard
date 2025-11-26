import streamlit as st

st.set_page_config(
    page_title="V-OptimAI home",
    page_icon="🏭",
)

st.write("# Welcome to V-Board! 👋")

st.sidebar.success("Select a demo above.")

st.markdown(
    """
    V-Boards is a dashboard service for quick POC development and demonstration purposes.
    It is specifically to demonstrate the final web-application used for data visualisation and data-driven modelling 
    of the Industrial IOT devices developed by V-OptimAI.

    **👈 Select a demo from the sidebar** to see some examples
    of what Streamlit can do!
    ### Want to learn more?
    - Book a one-to-one session. [Email us:📨](mailto:innovate@v-optimai.com?subject=One-to-one%20session%20for%20Web-App%20demo.)
    - Know more about our company. [Website: 📄][https://www.v-optimai.com]
"""
)