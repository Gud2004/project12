import streamlit as st
import os
import time
import tempfile
from langchain_groq import ChatGroq
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate
from langchain.chains import create_retrieval_chain
from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import PyPDFLoader
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get API keys
groq_api_key = os.getenv('GROQ_API_KEY')
google_api_key = os.getenv("GOOGLE_API_KEY", "your_default_api_key_here")
if not google_api_key or google_api_key == "your_default_api_key_here":
    st.warning("⚠️ Google API key not set properly. Please ensure it's correctly added in your .env file.")

os.environ["GOOGLE_API_KEY"] = google_api_key

# Page configuration
st.set_page_config(page_title="PDF Chatbot", layout="wide")
st.title("PDF Chatbot")

# Initialize session state variables
if 'processed_pdfs' not in st.session_state:
    st.session_state.processed_pdfs = False
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []
if 'vector_store' not in st.session_state:
    st.session_state.vector_store = None

# Function to process PDFs and create vector store
def process_pdfs(pdf_files):
    with st.spinner("Processing your PDFs... This may take a minute depending on file size."):

        try:
            # Initialize embeddings with the correct API key
            embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=google_api_key)

            # Process each PDF file
            all_docs = []
            for pdf_file in pdf_files:
                with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                    temp_file.write(pdf_file.read())
                    temp_path = temp_file.name
                
                # Load and process the PDF
                loader = PyPDFLoader(temp_path)
                docs = loader.load()
                
                # Add source metadata
                for doc in docs:
                    doc.metadata['source'] = pdf_file.name
                
                all_docs.extend(docs)
                os.unlink(temp_path)

            # Split documents into chunks
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
            splits = text_splitter.split_documents(all_docs)

            # Create vector store
            vector_store = FAISS.from_documents(splits, embeddings)

            return vector_store
            
        except Exception as e:
            st.error(f"Error processing PDFs: {str(e)}")
            return None

# Initialize LLM
@st.cache_resource
def get_llm():
    return ChatGroq(
        groq_api_key=groq_api_key,
        model_name="Llama3-8b-8192"
    )

# Create retrieval chain
def create_chain(vector_store):
    llm = get_llm()

    prompt = ChatPromptTemplate.from_template("""
    You are a helpful assistant that answers questions based on the provided PDF documents.
    
    <context>
    {context}
    </context>
    
    Question: {input}
    
    Answer the question based only on the provided context. If the information is not in the 
    context, say "I don't have enough information to answer this question based on the provided documents."
    
    Provide a clear, concise, and informative answer.
    """)
    
    document_chain = create_stuff_documents_chain(llm, prompt)
    retriever = vector_store.as_retriever(search_kwargs={"k": 5})
    return create_retrieval_chain(retriever, document_chain)

# Sidebar for PDF upload
with st.sidebar:
    st.header("Upload Documents")
    uploaded_files = st.file_uploader("Upload PDF files", accept_multiple_files=True, type=['pdf'])
    
    if uploaded_files:
        if st.button("Process Documents"):
            vector_store = process_pdfs(uploaded_files)
            if vector_store:
                st.session_state.vector_store = vector_store
                st.session_state.processed_pdfs = True
                st.success(f"✅ Successfully processed {len(uploaded_files)} PDF files")
            else:
                st.error("Failed to process documents")
    
    if st.session_state.processed_pdfs:
        st.sidebar.success("Documents processed and ready for questions")
    else:
        st.sidebar.info("Please upload and process documents first")
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("### How it works")
    st.sidebar.markdown("""1. Upload your PDF documents 2. Click 'Process Documents' 3. Ask questions about the content""")

# Main chat interface
st.markdown("### Ask questions about your documents")

for message in st.session_state.chat_history:
    if message["role"] == "user":
        st.chat_message("user").write(message["content"])
    else:
        st.chat_message("assistant").write(message["content"])

# Chat input
if prompt := st.chat_input("Ask a question about your PDFs..."):
    st.session_state.chat_history.append({"role": "user", "content": prompt})
    st.chat_message("user").write(prompt)

    if not st.session_state.processed_pdfs:
        response = "Please upload and process documents first using the sidebar."
        st.chat_message("assistant").write(response)
        st.session_state.chat_history.append({"role": "assistant", "content": response})
    else:
        with st.chat_message("assistant"):
            message_placeholder = st.empty()

            try:
                chain = create_chain(st.session_state.vector_store)
                start_time = time.time()
                response = chain.invoke({"input": prompt})

                elapsed_time = time.time() - start_time
                message_placeholder.write(response["answer"])
                st.caption(f"Response time: {elapsed_time:.2f} seconds")
                st.session_state.chat_history.append({"role": "assistant", "content": response["answer"]})

                with st.expander("View document sources"):
                    for i, doc in enumerate(response["context"]):
                        st.markdown(f"*Source {i+1}*: {doc.metadata.get('source', 'Unknown')} (Page {doc.metadata.get('page', 'Unknown')})")
                        st.markdown(f"{doc.page_content[:300]}...")
                        st.markdown("---")

            except Exception as e:
                error_msg = f"Error generating response: {str(e)}"
                message_placeholder.error(error_msg)
                st.session_state.chat_history.append({"role": "assistant", "content": error_msg})

if not st.session_state.processed_pdfs and not st.session_state.chat_history:
    st.info("👈 Start by uploading your PDF documents in the sidebar")
