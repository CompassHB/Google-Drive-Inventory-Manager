import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import re
from io import StringIO
import base64

# Configure page
st.set_page_config(
    page_title="📁 Google Drive Inventory Manager",
    page_icon="📁",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
if 'marked_for_archiving' not in st.session_state:
    st.session_state.marked_for_archiving = set()

def load_data(uploaded_file):
    """Load and process the CSV data"""
    if uploaded_file is not None:
        df = pd.read_csv(uploaded_file)
        
        # Clean and process data
        df['Last Updated'] = pd.to_datetime(df['Last Updated'], errors='coerce')
        df['Days Since Update'] = (datetime.now() - df['Last Updated']).dt.days
        
        # Create age categories
        def categorize_age(days):
            if pd.isna(days):
                return "Unknown"
            elif days <= 30:
                return "Recent (0-30 days)"
            elif days <= 90:
                return "Moderately Old (1-3 months)"
            elif days <= 365:
                return "Old (3-12 months)"
            else:
                return "Very Old (1+ years)"
        
        df['Age Category'] = df['Days Since Update'].apply(categorize_age)
        
        # Create folder hierarchy levels
        df['Folder Level'] = df['Folder Path'].str.count('/')
        df['Parent Folder'] = df['Folder Path'].str.extract(r'(.+)/[^/]+$').fillna('Root')
        
        return df
    return None

def get_color_for_age(age_category):
    """Return color based on file age"""
    colors = {
        "Recent (0-30 days)": "#2ECC71",      # Green
        "Moderately Old (1-3 months)": "#F39C12",  # Orange  
        "Old (3-12 months)": "#E74C3C",      # Red
        "Very Old (1+ years)": "#8B0000",    # Dark Red
        "Unknown": "#95A5A6"                 # Gray
    }
    return colors.get(age_category, "#95A5A6")

def ai_archive_suggestions(df):
    """Generate AI-powered archiving suggestions"""
    suggestions = []
    
    # Rule 1: Very old files with no recent activity
    very_old_files = df[
        (df['Age Category'] == 'Very Old (1+ years)') & 
        (df['Type'] == 'File')
    ]
    
    if len(very_old_files) > 0:
        suggestions.append({
            'category': 'Very Old Files',
            'count': len(very_old_files),
            'reason': 'Files not accessed in over 1 year',
            'confidence': 'High',
            'items': very_old_files['Name'].tolist()[:10]  # Show first 10
        })
    
    # Rule 2: Empty folders
    empty_folders = df[
        (df['Type'] == 'Folder') & 
        (df['Content Count'] == 0)
    ]
    
    if len(empty_folders) > 0:
        suggestions.append({
            'category': 'Empty Folders',
            'count': len(empty_folders),
            'reason': 'Folders containing no files',
            'confidence': 'High',
            'items': empty_folders['Name'].tolist()
        })
    
    # Rule 3: Duplicate or similar file names
    file_df = df[df['Type'] == 'File'].copy()
    if len(file_df) > 0:
        # Simple duplicate detection based on similar names
        duplicate_candidates = []
        seen_patterns = {}
        
        for idx, row in file_df.iterrows():
            # Remove common suffixes and create pattern
            name_clean = re.sub(r'(_copy|_v\d+|\(\d+\)|_final|_draft)', '', row['Name'].lower())
            name_pattern = re.sub(r'\.(pdf|docx?|xlsx?|pptx?)$', '', name_clean)
            
            if name_pattern in seen_patterns:
                duplicate_candidates.extend([seen_patterns[name_pattern], row['Name']])
            else:
                seen_patterns[name_pattern] = row['Name']
        
        if duplicate_candidates:
            suggestions.append({
                'category': 'Potential Duplicates',
                'count': len(set(duplicate_candidates)),
                'reason': 'Files with similar names that might be duplicates',
                'confidence': 'Medium',
                'items': list(set(duplicate_candidates))[:10]
            })
    
    # Rule 4: Large folders with old content
    old_folders = df[
        (df['Type'] == 'Folder') & 
        (df['Age Category'].isin(['Old (3-12 months)', 'Very Old (1+ years)'])) &
        (df['Content Count'] > 10)
    ]
    
    if len(old_folders) > 0:
        suggestions.append({
            'category': 'Large Old Folders',
            'count': len(old_folders),
            'reason': 'Folders with many files that haven\'t been updated recently',
            'confidence': 'Medium',
            'items': old_folders['Name'].tolist()[:5]
        })
    
    return suggestions

def create_folder_tree_view(df):
    """Create collapsible folder tree view"""
    if df is None or len(df) == 0:
        return
    
    # Group by folder path
    folders = df[df['Type'] == 'Folder'].copy()
    files = df[df['Type'] == 'File'].copy()
    
    # Create folder hierarchy
    folder_structure = {}
    
    # Build folder structure
    for _, folder in folders.iterrows():
        path_parts = folder['Folder Path'].split('/')
        current_dict = folder_structure
        
        for part in path_parts:
            if part not in current_dict:
                current_dict[part] = {'folders': {}, 'files': [], 'info': None}
            current_dict = current_dict[part]['folders']
        
        # Store folder info at the final level
        path_parts = folder['Folder Path'].split('/')
        current_dict = folder_structure
        for part in path_parts[:-1]:
            current_dict = current_dict[part]['folders']
        current_dict[path_parts[-1]]['info'] = folder
    
    # Add files to their respective folders
    for _, file in files.iterrows():
        path_parts = file['Folder Path'].split('/')
        current_dict = folder_structure
        
        for part in path_parts:
            if part not in current_dict:
                current_dict[part] = {'folders': {}, 'files': [], 'info': None}
            current_dict = current_dict[part]['folders']
        
        # Add file to the folder
        path_parts = file['Folder Path'].split('/')
        current_dict = folder_structure
        for part in path_parts:
            current_dict = current_dict[part]['folders']
        
        # Go back one level to add to files list
        path_parts = file['Folder Path'].split('/')
        current_dict = folder_structure
        for part in path_parts[:-1]:
            current_dict = current_dict[part]['folders']
        if path_parts:
            current_dict[path_parts[-1]]['files'].append(file)
    
    # Display folder tree
    def display_folder(name, content, level=0):
        indent = "　" * level  # Japanese space for better indentation
        
        # Folder header
        folder_info = content.get('info')
        if folder_info is not None:
            age_color = get_color_for_age(folder_info['Age Category'])
            file_count = len(content['files'])
            subfolder_count = len([k for k, v in content['folders'].items() if v['info'] is not None])
            
            col1, col2, col3 = st.columns([1, 8, 1])
            
            with col1:
                expanded = st.checkbox("", key=f"folder_{name}_{level}", value=False)
            
            with col2:
                st.markdown(f"""
                <div style='background-color: {age_color}20; padding: 8px; border-left: 4px solid {age_color}; margin: 2px 0;'>
                    {indent}📁 <strong>{name}</strong> 
                    <small>({file_count} files, {subfolder_count} subfolders)</small>
                </div>
                """, unsafe_allow_html=True)
            
            with col3:
                archive_key = f"archive_folder_{folder_info['Name']}_{level}"
                if st.checkbox("Archive", key=archive_key):
                    st.session_state.marked_for_archiving.add(folder_info['Name'])
                elif archive_key in st.session_state and not st.session_state[archive_key]:
                    st.session_state.marked_for_archiving.discard(folder_info['Name'])
            
            if expanded:
                # Show files in this folder
                for file_info in content['files']:
                    age_color = get_color_for_age(file_info['Age Category'])
                    col1, col2, col3 = st.columns([1, 8, 1])
                    
                    with col2:
                        st.markdown(f"""
                        <div style='background-color: {age_color}10; padding: 4px; border-left: 2px solid {age_color}; margin: 1px 0; margin-left: 20px;'>
                            {indent}　📄 {file_info['Name']} 
                            <small>({file_info['Age Category']})</small>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    with col3:
                        archive_key = f"archive_file_{file_info['Name']}_{level}"
                        if st.checkbox("", key=archive_key):
                            st.session_state.marked_for_archiving.add(file_info['Name'])
                
                # Show subfolders
                for subfolder_name, subfolder_content in content['folders'].items():
                    if subfolder_content['info'] is not None:
                        display_folder(subfolder_name, subfolder_content, level + 1)
    
    # Display root level folders
    for folder_name, folder_content in folder_structure.items():
        if folder_content['info'] is not None:
            display_folder(folder_name, folder_content)

def create_download_link(df, filename):
    """Create download link for filtered data"""
    csv = df.to_csv(index=False)
    b64 = base64.b64encode(csv.encode()).decode()
    href = f'<a href="data:file/csv;base64,{b64}" download="{filename}">📥 Download Filtered Data as CSV</a>'
    return href

# Main App
def main():
    st.title("📁 Google Drive Inventory Manager")
    st.markdown("---")
    
    # File upload
    uploaded_file = st.file_uploader(
        "Upload your Google Drive inventory CSV file",
        type=['csv'],
        help="Upload the CSV export from your Google Drive inventory spreadsheet"
    )
    
    if uploaded_file is None:
        st.info("👆 Please upload your CSV file to get started!")
        st.markdown("""
        ### Expected CSV Format:
        Your CSV should have these columns:
        - **Name**: Item name
        - **Type**: "File" or "Folder"  
        - **URL**: Google Drive URL
        - **Last Updated**: Date last modified
        - **Last Edited By**: Person who last edited
        - **Last Editor Email**: Email of last editor
        - **Folder Path**: Full path to the item
        - **Content Count**: Number of items in folder
        """)
        return
    
    # Load data
    df = load_data(uploaded_file)
    if df is None:
        st.error("Could not load the CSV file. Please check the format.")
        return
    
    # Sidebar filters
    st.sidebar.header("🔍 Filters")
    
    # File/Folder filter
    type_filter = st.sidebar.selectbox(
        "Show:",
        ["All Items", "Files Only", "Folders Only"]
    )
    
    # Search box
    search_term = st.sidebar.text_input(
        "🔎 Search by name:",
        placeholder="Enter file or folder name..."
    )
    
    # Date range slider
    if not df['Last Updated'].isna().all():
        min_date = df['Last Updated'].min().date()
        max_date = df['Last Updated'].max().date()
        
        date_range = st.sidebar.date_input(
            "📅 Last Updated Date Range:",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date
        )
    else:
        date_range = None
    
    # Age category filter
    age_categories = st.sidebar.multiselect(
        "📊 Age Categories:",
        options=df['Age Category'].unique(),
        default=df['Age Category'].unique()
    )
    
    # Apply filters
    filtered_df = df.copy()
    
    if type_filter == "Files Only":
        filtered_df = filtered_df[filtered_df['Type'] == 'File']
    elif type_filter == "Folders Only":
        filtered_df = filtered_df[filtered_df['Type'] == 'Folder']
    
    if search_term:
        filtered_df = filtered_df[
            filtered_df['Name'].str.contains(search_term, case=False, na=False)
        ]
    
    if date_range and len(date_range) == 2:
        filtered_df = filtered_df[
            (filtered_df['Last Updated'].dt.date >= date_range[0]) &
            (filtered_df['Last Updated'].dt.date <= date_range[1])
        ]
    
    filtered_df = filtered_df[filtered_df['Age Category'].isin(age_categories)]
    
    # Main content tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Overview", "🗂️ Folder Tree", "🤖 AI Suggestions", "📋 Data Table"])
    
    with tab1:
        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Items", len(filtered_df))
        with col2:
            st.metric("Files", len(filtered_df[filtered_df['Type'] == 'File']))
        with col3:
            st.metric("Folders", len(filtered_df[filtered_df['Type'] == 'Folder']))
        with col4:
            st.metric("Marked for Archiving", len(st.session_state.marked_for_archiving))
        
        # Charts
        col1, col2 = st.columns(2)
        
        with col1:
            # Age distribution pie chart
            age_counts = filtered_df['Age Category'].value_counts()
            fig_pie = px.pie(
                values=age_counts.values,
                names=age_counts.index,
                title="File Age Distribution",
                color_discrete_map={
                    "Recent (0-30 days)": "#2ECC71",
                    "Moderately Old (1-3 months)": "#F39C12",
                    "Old (3-12 months)": "#E74C3C", 
                    "Very Old (1+ years)": "#8B0000",
                    "Unknown": "#95A5A6"
                }
            )
            st.plotly_chart(fig_pie, use_container_width=True)
        
        with col2:
            # File type distribution
            type_counts = filtered_df['Type'].value_counts()
            fig_bar = px.bar(
                x=type_counts.index,
                y=type_counts.values,
                title="Files vs Folders",
                color=type_counts.index,
                color_discrete_map={"File": "#3498DB", "Folder": "#9B59B6"}
            )
            st.plotly_chart(fig_bar, use_container_width=True)
        
        # Timeline chart
        if not filtered_df['Last Updated'].isna().all():
            timeline_data = filtered_df.groupby([
                filtered_df['Last Updated'].dt.to_period('M'),
                'Type'
            ]).size().reset_index(name='count')
            timeline_data['Last Updated'] = timeline_data['Last Updated'].astype(str)
            
            fig_timeline = px.line(
                timeline_data,
                x='Last Updated',
                y='count',
                color='Type',
                title="Update Activity Over Time",
                markers=True
            )
            fig_timeline.update_xaxis(title="Month")
            fig_timeline.update_yaxis(title="Number of Updates")
            st.plotly_chart(fig_timeline, use_container_width=True)
    
    with tab2:
        st.header("🗂️ Collapsible Folder Tree")
        st.markdown("*Click checkboxes to expand folders and mark items for archiving*")
        
        if len(filtered_df) > 0:
            create_folder_tree_view(filtered_df)
        else:
            st.info("No items match your current filters.")
    
    with tab3:
        st.header("🤖 AI Archive Suggestions")
        st.markdown("*Based on file age, usage patterns, and content analysis*")
        
        suggestions = ai_archive_suggestions(filtered_df)
        
        if suggestions:
            for suggestion in suggestions:
                confidence_color = {
                    'High': '#E74C3C',
                    'Medium': '#F39C12', 
                    'Low': '#F1C40F'
                }[suggestion['confidence']]
                
                with st.expander(f"🎯 {suggestion['category']} ({suggestion['count']} items) - {suggestion['confidence']} Confidence"):
                    st.markdown(f"""
                    **Reason:** {suggestion['reason']}
                    
                    **Confidence:** <span style='color: {confidence_color}; font-weight: bold;'>{suggestion['confidence']}</span>
                    
                    **Sample Items:**
                    """, unsafe_allow_html=True)
                    
                    for item in suggestion['items'][:5]:
                        st.markdown(f"• {item}")
                    
                    if len(suggestion['items']) > 5:
                        st.markdown(f"*... and {len(suggestion['items']) - 5} more items*")
                    
                    if st.button(f"Mark all {suggestion['category']} for archiving", key=f"mark_{suggestion['category']}"):
                        st.session_state.marked_for_archiving.update(suggestion['items'])
                        st.success(f"Marked {len(suggestion['items'])} items for archiving!")
        else:
            st.info("No specific archiving suggestions found. Your drive looks well-organized! 🎉")
    
    with tab4:
        st.header("📋 Filtered Data Table")
        
        if len(filtered_df) > 0:
            # Add color coding to the dataframe display
            def highlight_age(row):
                color = get_color_for_age(row['Age Category'])
                return [f'background-color: {color}20' if col == 'Age Category' else '' for col in row.index]
            
            # Display data with color coding
            styled_df = filtered_df.style.apply(highlight_age, axis=1)
            st.dataframe(styled_df, use_container_width=True)
            
            # Download button
            st.markdown(create_download_link(filtered_df, "filtered_drive_inventory.csv"), unsafe_allow_html=True)
            
        else:
            st.info("No items match your current filters.")
    
    # Show marked items for archiving
    if st.session_state.marked_for_archiving:
        st.sidebar.markdown("---")
        st.sidebar.header("🗂️ Marked for Archiving")
        st.sidebar.markdown(f"**{len(st.session_state.marked_for_archiving)} items marked**")
        
        if st.sidebar.button("📋 View All Marked Items"):
            st.sidebar.write("Marked items:")
            for item in list(st.session_state.marked_for_archiving)[:10]:
                st.sidebar.markdown(f"• {item}")
            if len(st.session_state.marked_for_archiving) > 10:
                st.sidebar.markdown(f"*... and {len(st.session_state.marked_for_archiving) - 10} more*")
        
        if st.sidebar.button("🗑️ Clear All Marked"):
            st.session_state.marked_for_archiving.clear()
            st.experimental_rerun()

if __name__ == "__main__":
    main()