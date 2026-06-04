import sys
import ctypes

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

if __name__ == "__main__":
    # Desktop duplication API often performs best or requires admin for certain games
    # But it's not strictly required.
    from ui import RecorderUI
    
    app = RecorderUI()
    app.mainloop()
