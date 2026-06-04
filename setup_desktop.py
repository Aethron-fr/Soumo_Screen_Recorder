import os
import sys
from PIL import Image, ImageDraw
import win32com.client

def create_icon(icon_path):
    print("Generating icon...")
    size = (256, 256)
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((10, 10, 246, 246), radius=40, fill=(30, 30, 30, 255))
    draw.ellipse((68, 68, 188, 188), fill=(231, 76, 60, 255))
    draw.ellipse((58, 58, 198, 198), outline=(255, 255, 255, 100), width=5)

    img.save(icon_path, format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (32, 32)])
    print(f"Icon saved to {icon_path}")

def create_shortcut():
    print("Creating desktop shortcut...")
    desktop = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")
    if not os.path.exists(desktop):
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        
    shortcut_path = os.path.join(desktop, "Soumo Screen Recorder PRO.lnk")
    
    target_dir = os.path.dirname(os.path.abspath(__file__))
    target_path = os.path.join(target_dir, "run.bat")
    icon_path = os.path.join(target_dir, "icon.ico")
    
    if not os.path.exists(icon_path):
        create_icon(icon_path)
        
    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(shortcut_path)
    shortcut.Targetpath = target_path
    shortcut.WorkingDirectory = target_dir
    shortcut.IconLocation = icon_path
    shortcut.save()
    print(f"Shortcut created successfully at: {shortcut_path}")

if __name__ == "__main__":
    create_shortcut()
