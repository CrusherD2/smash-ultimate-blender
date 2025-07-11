from bpy.types import Panel

class SUB_PT_update_plugin(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Ultimate'
    bl_label = 'Update Available!'

    @classmethod
    def poll(cls, context):
        from .version_check import UPDATE_AVAILABLE
        return UPDATE_AVAILABLE
    
    def draw(self, context):
        from ...__init__ import bl_info
        from .version_check import LATEST_COMMIT_SHA, LATEST_COMMIT_MESSAGE, LATEST_COMMIT_DATE, CURRENT_COMMIT_SHA, UPDATE_STATUS, UPDATE_DOWNLOAD_PROGRESS

        layout = self.layout
        layout.use_property_split = False
        
        # Commit information
        layout.row().label(text="A new update is available on animation-workflow branch!")
        
        # Current and latest commit info
        current_version = bl_info['version']
        layout.row().label(text=f"Plugin version: v{current_version[0]}.{current_version[1]}.{current_version[2]}")
        
        if CURRENT_COMMIT_SHA:
            layout.row().label(text=f"Current commit: {CURRENT_COMMIT_SHA[:8]}")
        else:
            layout.row().label(text="Current commit: Unknown")
            
        if LATEST_COMMIT_SHA:
            layout.row().label(text=f"Latest commit: {LATEST_COMMIT_SHA[:8]}")
            
        if LATEST_COMMIT_DATE:
            layout.row().label(text=f"Date: {LATEST_COMMIT_DATE[:10]}")  # Show just the date part
            
        if LATEST_COMMIT_MESSAGE:
            # Truncate long commit messages
            message = LATEST_COMMIT_MESSAGE[:60] + "..." if len(LATEST_COMMIT_MESSAGE) > 60 else LATEST_COMMIT_MESSAGE
            layout.row().label(text=f"Message: {message}")
        
        layout.separator()
        
        # Status and buttons based on current update state
        if UPDATE_STATUS == "idle":
            layout.row().operator("sub.check_for_updates", text="Refresh Update Check")
            layout.row().operator("sub.download_update", text="Download Update")
            
        elif UPDATE_STATUS == "checking":
            layout.row().label(text="Checking for updates...", icon='INFO')
            
        elif UPDATE_STATUS == "downloading":
            layout.row().label(text="Downloading update...", icon='IMPORT')
            # Progress bar
            row = layout.row()
            row.scale_y = 0.5
            progress_text = f"Progress: {UPDATE_DOWNLOAD_PROGRESS:.1%}"
            row.progress(factor=UPDATE_DOWNLOAD_PROGRESS, text=progress_text)
            
        elif UPDATE_STATUS == "ready_to_install":
            layout.row().label(text="Update downloaded successfully!", icon='CHECKMARK')
            layout.row().operator("sub.install_update", text="Install Update")
            layout.row().operator("sub.download_update", text="Re-download Update")
            
        elif UPDATE_STATUS == "installing":
            layout.row().label(text="Installing update...", icon='FILE_REFRESH')
            layout.row().label(text="Please wait, do not close Blender!")
            
        elif UPDATE_STATUS == "ready_to_restart":
            layout.row().label(text="Update installed successfully!", icon='CHECKMARK')
            layout.row().label(text="Restart Blender to complete the update:")
            col = layout.column()
            col.scale_y = 1.5
            col.operator("sub.restart_blender", text="Restart Blender Now", icon='FILE_REFRESH')
            layout.separator()
            layout.row().label(text="Warning: Unsaved changes will be lost!", icon='ERROR')

class SUB_PT_updater_settings(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Ultimate'
    bl_label = 'Plugin Updater'
    bl_parent_id = "SUB_PT_update_plugin"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        from .version_check import UPDATE_AVAILABLE
        return UPDATE_AVAILABLE
    
    def draw(self, context):
        from .version_check import UPDATE_STATUS

        layout = self.layout
        layout.use_property_split = False
        
        # Manual controls
        layout.row().label(text="Manual Controls:")
        layout.row().operator("sub.check_for_updates", text="Check for Updates", icon='FILE_REFRESH')
        
        if UPDATE_STATUS not in ["downloading", "installing"]:
            layout.row().operator("sub.download_update", text="Force Re-download", icon='IMPORT')
        
        # Information
        layout.separator()
        layout.row().label(text="Repository: CrusherD2/smash-ultimate-blender")
        layout.row().label(text="Branch: animation-workflow")
        layout.row().label(text="Updates monitor commits on this branch")
