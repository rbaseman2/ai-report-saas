import streamlit as st

# Must be the first Streamlit call
st.set_page_config(
    page_title="AI Report – Business Document Summaries",
    page_icon="📄",
    layout="wide",
)

st.title("📄 AI Report")
st.subheader("Turn long business documents into clear, client-ready summaries")

st.write(
    """
AI Report helps consultants, freelancers, and small teams quickly turn long reports, 
proposals, meeting notes, and PDFs into concise, easy-to-share summaries.

Upload your content once, and let AI create a summary you can send to clients, 
stakeholders, or your internal team.
"""
)

st.markdown("---")

col1, col2 = st.columns(2)

with col1:
    st.markdown("### How it works")
    st.markdown(
        """
1. **Upload your document** – PDF, Word, text, or CSV  
2. **AI analyzes the content** – finds the key points, risks, and next steps  
3. **Get a clean summary** – ready to paste into emails, reports, or slide decks  
        """
    )

    st.markdown("### What you can summarize")
    st.markdown(
        """
- Project proposals and SOWs  
- Meeting notes or discovery calls  
- Research reports and analysis  
- Process documentation and SOPs  
- CSV exports (e.g. metrics, logs, simple datasets)  
        """
    )

with col2:
    st.markdown("### Plans that grow with you")
    st.markdown(
        """
- **Free** – Try the tool with shorter inputs and simpler summaries  
- **Basic** – Perfect for solo users summarizing a few documents each month  
- **Pro** – For consultants and power users handling client work regularly  
- **Enterprise** – For teams that need higher volume and support  
        """
    )

st.markdown("---")

st.markdown(
    """
**Next steps**

- Go to the **Billing** page to choose a plan  
- Then use **Upload Data** to generate your first summary  
"""
)
