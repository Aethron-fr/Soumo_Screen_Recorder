import tkinter as tk
from tkinter import Toplevel

class RegionSelector:
    def __init__(self, on_selected_callback):
        self.callback = on_selected_callback
        
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.3)
        self.root.attributes("-topmost", True)
        self.root.attributes("-fullscreen", True)
        self.root.config(cursor="crosshair")
        self.root.configure(background='black')
        
        # Canvas to draw the rectangle
        self.canvas = tk.Canvas(self.root, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.start_x = None
        self.start_y = None
        self.rect = None

        self.root.bind("<ButtonPress-1>", self.on_button_press)
        self.root.bind("<B1-Motion>", self.on_move_press)
        self.root.bind("<ButtonRelease-1>", self.on_button_release)
        self.root.bind("<Escape>", self.on_cancel)

    def on_button_press(self, event):
        self.start_x = self.canvas.canvasx(event.x)
        self.start_y = self.canvas.canvasy(event.y)

        if not self.rect:
            self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, 1, 1, outline='red', width=3, fill="gray", stipple="gray25")

    def on_move_press(self, event):
        curX = self.canvas.canvasx(event.x)
        curY = self.canvas.canvasy(event.y)
        self.canvas.coords(self.rect, self.start_x, self.start_y, curX, curY)

    def on_button_release(self, event):
        end_x = self.canvas.canvasx(event.x)
        end_y = self.canvas.canvasy(event.y)

        left = int(min(self.start_x, end_x))
        top = int(min(self.start_y, end_y))
        right = int(max(self.start_x, end_x))
        bottom = int(max(self.start_y, end_y))
        
        self.root.destroy()
        
        if right - left > 10 and bottom - top > 10:
            self.callback((left, top, right, bottom))
        else:
            self.callback(None)

    def on_cancel(self, event):
        self.root.destroy()
        self.callback(None)

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    def on_sel(region):
        print("Selected:", region)
    rs = RegionSelector(on_sel)
    rs.run()
