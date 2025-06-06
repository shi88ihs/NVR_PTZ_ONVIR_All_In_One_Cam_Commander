#!/usr/bin/env python3
# CamCommander PTZ & NVR GUI v9

import tkinter as tk
from tkinter import ttk, messagebox
from onvif import ONVIFCamera
import json
import os
from pathlib import Path
import sys
import subprocess
import re
import webbrowser
import glob
import datetime

class PTZCameraControl:
    def __init__(self):
        print("[DEBUG] Starting PTZCameraControl...")
        self.save_dir = os.path.expanduser("~/Videos/V380_Motion_Triggered_Vids")
        self.motion_conf_path = os.path.join(self.save_dir, "motion.conf")
        action = {}
        self.ip, self.username, self.password, action = self.get_ip_user_pass_with_action()
        print(f"[DEBUG] Selected IP: {self.ip}")
        print(f"[DEBUG] Selected Username: {self.username}")
        self.config = self.load_config()
        print(f"[DEBUG] Loaded config: {self.config}")

        self.root = tk.Tk()
        self.root.title("CamCommander - PTZ Ctrl + NVR Recording GUI")
        self.root.geometry("380x640")

        self.status_label = tk.Label(
            self.root, text="Disconnected", fg="red",
            font=("Helvetica", 22, "bold")
        )
        self.status_label.pack(pady=10)

        self.ptz = None
        self.media = None
        self.profile = None
        self.token = None

        self.motion_proc = None
        self.setup_ui()
        self.connect_camera()
        # --- Quick-launch ---
        if action.get("motioneye") and action.get("mpv"):
            self.open_motioneye(quiet=True)
            self.launch_mpv_stream()
        elif action.get("motioneye"):
            self.open_motioneye(quiet=True)
        elif action.get("mpv"):
            self.launch_mpv_stream()
        self.root.mainloop()

    def get_ip_user_pass_with_action(self):
        ips_path = Path.home() / '.ptz_ips.json'
        creds_path = Path.home() / '.ptz_camera_creds.json'

        previous_ips = []
        if ips_path.exists():
            with open(ips_path) as f:
                previous_ips = json.load(f)
            print(f"[DEBUG] Loaded previous IPs: {previous_ips}")

        creds = {}
        if creds_path.exists():
            with open(creds_path) as f:
                creds = json.load(f)
            print(f"[DEBUG] Loaded previous creds for IPs: {list(creds.keys())}")

        if len(sys.argv) > 1:
            ip = sys.argv[1]
            user = creds.get(ip, {}).get("username", "")
            passwd = creds.get(ip, {}).get("password", "")
            if ip not in previous_ips:
                previous_ips.append(ip)
                with open(ips_path, 'w') as f:
                    json.dump(previous_ips, f)
            return ip, user, passwd, {}

        root = tk.Tk()
        root.title("Cam Commander GUI")
        root.withdraw()
        ip = None
        user = ""
        passwd = ""
        action = {}

        def on_select():
            nonlocal ip, user, passwd
            ip = combo_ip.get().strip()
            user = entry_user.get().strip()
            passwd = entry_pass.get().strip()
            prompt_buttons.deiconify()

        prompt = tk.Toplevel(root)
        prompt.title("Cam Commander Login")
        tk.Label(prompt, text="Camera IP:").grid(row=0, column=0, sticky="e", padx=5, pady=5)
        combo_ip = ttk.Combobox(prompt, values=previous_ips)
        combo_ip.grid(row=0, column=1, padx=5, pady=5)
        if previous_ips:
            combo_ip.set(previous_ips[-1])
        combo_ip.focus_set()

        tk.Label(prompt, text="Username:").grid(row=1, column=0, sticky="e", padx=5, pady=5)
        entry_user = ttk.Entry(prompt)
        entry_user.grid(row=1, column=1, padx=5, pady=5)
        prefill_user = creds.get(previous_ips[-1], {}).get("username", "") if previous_ips else ""
        entry_user.insert(0, prefill_user)

        tk.Label(prompt, text="Password:").grid(row=2, column=0, sticky="e", padx=5, pady=5)
        entry_pass = ttk.Entry(prompt, show="*")
        entry_pass.grid(row=2, column=1, padx=5, pady=5)
        prefill_pass = creds.get(previous_ips[-1], {}).get("password", "") if previous_ips else ""
        entry_pass.insert(0, prefill_pass)

        btn = tk.Button(prompt, text="Next", command=on_select)
        btn.grid(row=3, column=0, columnspan=2, pady=8)
        prompt.protocol("WM_DELETE_WINDOW", root.quit)

        prompt_buttons = tk.Toplevel(root)
        prompt_buttons.title("Launch Options")
        prompt_buttons.withdraw()
        tk.Label(prompt_buttons, text="Quick Launch Options", font=("Helvetica", 12, "bold")).pack(pady=(7,3))
        tk.Label(prompt_buttons, text="After login, what do you want to launch?\n\n", font=("Helvetica", 9)).pack()

        def do_launch(me, mpv):
            nonlocal action
            action = {"motioneye": me, "mpv": mpv}
            prompt_buttons.destroy()
            prompt.destroy()
            root.quit()

        tk.Button(prompt_buttons, text="1. Launch MotionEye", width=22, command=lambda: do_launch(True, False)).pack(pady=2)
        tk.Button(prompt_buttons, text="2. Launch MPV", width=22, command=lambda: do_launch(False, True)).pack(pady=2)
        tk.Button(prompt_buttons, text="3. Launch Both", width=22, command=lambda: do_launch(True, True)).pack(pady=2)
        tk.Button(prompt_buttons, text="4. None / Decide Later", width=22, command=lambda: do_launch(False, False)).pack(pady=(2,6))

        root.mainloop()
        prompt_buttons.destroy()
        prompt.destroy()
        root.destroy()

        if not ip:
            print("[DEBUG] No IP address entered. Exiting.")
            sys.exit(1)
        if ip not in previous_ips:
            previous_ips.append(ip)
            with open(ips_path, 'w') as f:
                json.dump(previous_ips, f)
        if not user: user = ""
        if not passwd: passwd = ""
        creds[ip] = {"username": user, "password": passwd}
        with open(creds_path, "w") as f:
            json.dump(creds, f)
        return ip, user, passwd, action

    def load_config(self):
        config_path = Path.home() / '.ptz_config.json'
        default_config = {
            'ip': self.ip,
            'port': 8899,
            'username': self.username,
            'password': self.password
        }
        try:
            if config_path.exists():
                with open(config_path) as f:
                    config = json.load(f)
                print(f"[DEBUG] Loaded config from file: {config}")
            else:
                config = default_config
                print(f"[DEBUG] Using default config: {config}")

            config['ip'] = self.ip
            config['username'] = self.username
            config['password'] = self.password
            if 'port' not in config:
                config['port'] = default_config['port']
            return config
        except Exception as e:
            print(f"[DEBUG] Error loading config: {e}")
            sys.exit(1)

    def connect_camera(self):
        print(f"[DEBUG] Connecting to camera at {self.config['ip']}:{self.config['port']}")
        print(f"[DEBUG] Username: {self.config['username']}, Password: {self.config['password']}")
        try:
            wsdl_path = '/home/x/onvif/wsdl/'
            if not Path(wsdl_path).is_dir():
                raise Exception(f"WSDL path not found: {wsdl_path}")
            self.camera = ONVIFCamera(
                self.config['ip'],
                self.config['port'],
                self.config['username'],
                self.config['password'],
                wsdl_path
            )
            self.media = self.camera.create_media_service()
            self.ptz = self.camera.create_ptz_service()
            self.profile = self.media.GetProfiles()[0]
            self.token = self.profile.token
            print(f"[DEBUG] Connected to camera. Profile token: {self.token}")
            self.update_status("Connected", "green")
        except Exception as e:
            self.ptz = None  # Explicitly set to None on error
            self.token = None
            self.update_status("Connection Failed", "red")
            messagebox.showerror("Error", f"Failed to connect to camera: {str(e)}")

    def launch_mpv_stream(self):
        username = self.config.get('username', '')
        password = self.config.get('password', '')
        ip = self.config.get('ip')
        rtsp_url = f"rtsp://{username}:{password}@{ip}:554/Streaming/Channels/101"
        rtsp_url = rtsp_url.replace("::", ":")
        print(f"[DEBUG] Attempting to launch /usr/bin/mpv with RTSP URL: {rtsp_url}")
        try:
            subprocess.Popen([
                '/usr/bin/mpv',
                '--demuxer-lavf-o=rtsp_transport=tcp',
                rtsp_url
            ])
            print("[DEBUG] mpv launched successfully.")
        except Exception as e:
            print(f"[DEBUG] Failed to launch mpv: {e}")

    def setup_ui(self):
        print("[DEBUG] Setting up UI...")

        # --- MotionEye blue icon at the top (decorative, 2x stretch) ---
        try:
            icon_path = os.path.join(os.path.dirname(__file__), "icons", "MotionEye-Blue-64x64-Icon.png")
            self.icon_img = tk.PhotoImage(file=icon_path)
            if hasattr(self.icon_img, "zoom"):
                self.icon_img = self.icon_img.zoom(2, 2)
            icon_label = tk.Label(self.root, image=self.icon_img)
            icon_label.pack(pady=(10, 0))
        except Exception as e:
            print(f"[DEBUG] Icon could not be loaded: {e}")

        # --- PTZ Control Buttons ---
        control_frame = ttk.Frame(self.root)
        control_frame.pack(pady=18)
        btn_size = 24
        btn_font = ("Helvetica", 12, "bold")
        buttons = [
            ('↖', -1, 1), ('↑', 0, 1), ('↗', 1, 1),
            ('←', -1, 0), ('■', 0, 0), ('→', 1, 0),
            ('↙', -1, -1), ('↓', 0, -1), ('↘', 1, -1)
        ]
        for i, (label, dx, dy) in enumerate(buttons):
            if label == '■':
                btn = tk.Button(
                    control_frame,
                    text=label,
                    width=btn_size//10, height=btn_size//20,
                    font=btn_font,
                    bg="#ddd",
                    relief="raised",
                    bd=3,
                    command=self.go_to_center
                )
            else:
                btn = tk.Button(
                    control_frame,
                    text=label,
                    width=btn_size//10, height=btn_size//20,
                    font=btn_font,
                    bg="#ddd",
                    relief="raised",
                    bd=3,
                    command=lambda x=dx, y=dy: self.move(x, y)
                )
            btn.grid(row=i//3, column=i%3, padx=2, pady=2, sticky="nsew")
        for i in range(3):
            control_frame.grid_rowconfigure(i, weight=1, minsize=btn_size)
            control_frame.grid_columnconfigure(i, weight=1, minsize=btn_size)

        self.motion_btn = tk.Button(
            self.root,
            text="🎬 Start Motion Detection & Recording",
            font=("Helvetica", 11, "bold"),
            command=self.start_motion,
            bg="#ddebf7", activebackground="#c5e0fa"
        )
        self.motion_btn.pack(pady=8)

        self.stop_motion_btn = tk.Button(
            self.root,
            text="🛑 Stop Motion Detection & Recording",
            font=("Helvetica", 11, "bold"),
            command=self.stop_motion,
            state='disabled',
            bg="#fbeee6", activebackground="#ffe5d0"
        )
        self.stop_motion_btn.pack(pady=2)

        # --- MPV Stream Button (with icon) ---
        mpv_icon_path = os.path.join(os.path.dirname(__file__), "icons", "mpv-64x64-icon.png")

        if os.path.exists(mpv_icon_path):
            try:
                self.mpv_icon_img = tk.PhotoImage(file=mpv_icon_path)
                mpv_btn = tk.Button(
                    self.root, image=self.mpv_icon_img, compound="left",
                    text="  Start MPV Stream  ", font=("Helvetica", 12, "bold"),
                    command=self.launch_mpv_stream
                )
                mpv_btn.pack(pady=(10, 0))
            except Exception as e:
                print(f"[DEBUG] MPV icon could not be loaded: {e}")
                tk.Button(
                    self.root, text="Start MPV Stream",
                    font=("Helvetica", 12, "bold"),
                    command=self.launch_mpv_stream
                ).pack(pady=(10, 0))
        else:
            tk.Button(
                self.root, text="Start MPV Stream",
                font=("Helvetica", 12, "bold"),
                command=self.launch_mpv_stream
            ).pack(pady=(10, 0))

        tk.Label(self.root).pack(expand=True)

        save_dir_frame = tk.Frame(self.root)
        save_dir_frame.pack(pady=(0, 2))
        dir_label = tk.Label(save_dir_frame, text=f"🎬 Saved Videos: {self.save_dir}", fg="#2d4e73", font=("Helvetica", 10, "bold"))
        dir_label.pack(side="left", padx=(2, 5))
        play_btn = tk.Button(save_dir_frame, text="▶️ Play All", font=("Helvetica", 10, "bold"), command=self.play_videos)
        play_btn.pack(side="left")
        refresh_btn = tk.Button(save_dir_frame, text="🔄 Refresh", font=("Helvetica", 10, "bold"), command=self.update_video_summary)
        refresh_btn.pack(side="left", padx=(4, 0))

        self.video_summary_label = tk.Label(self.root, text="", font=("Helvetica", 9))
        self.video_summary_label.pack(pady=(0, 6))
        self.update_video_summary()

        try:
            laptop_icon_path = os.path.join(
                os.path.dirname(__file__), "icons", "Laptop-Ip-Cam-WebPage-Icon-Scaled-64x64.png"
            )
            self.laptop_icon_img = tk.PhotoImage(file=laptop_icon_path)
            laptop_btn = tk.Button(
                self.root,
                image=self.laptop_icon_img,
                borderwidth=0,
                highlightthickness=0,
                command=self.open_motioneye,
                cursor="hand2",
                bg="#f5f5f5",
                activebackground="#e0e0e0"
            )
            laptop_btn.pack(pady=(0, 1), side="bottom")
        except Exception as e:
            print(f"[DEBUG] Laptop icon could not be loaded: {e}")

        self.motioneye_url = "http://localhost:8765"
        link_label = tk.Label(
            self.root,
            text="Click Here to Open the Motion Eye Local Web UI:\nlocalhost:8765",
            fg="#1379ec",  # deep blue
            cursor="hand2",
            font=("Helvetica", 20, "bold", "underline"),
            wraplength=360,
            justify="center"
        )
        link_label.pack(pady=(0, 18), side="bottom")
        link_label.bind("<Button-1>", lambda e: self.open_motioneye())

        print("[DEBUG] UI setup complete.")

    def update_video_summary(self):
        vid_types = ("*.mp4", "*.mkv", "*.avi")
        files = []
        for vt in vid_types:
            files.extend(glob.glob(os.path.join(self.save_dir, vt)))
        num_files = len(files)
        if num_files == 0:
            summary = "No saved videos yet."
        else:
            times = [os.path.getmtime(f) for f in files]
            sizes = [os.path.getsize(f) for f in files]
            first_time = datetime.datetime.fromtimestamp(min(times)).strftime('%Y-%m-%d %H:%M')
            last_time = datetime.datetime.fromtimestamp(max(times)).strftime('%Y-%m-%d %H:%M')
            total_mb = sum(sizes) / (1024 * 1024)
            summary = f"Count: {num_files} | Oldest: {first_time} | Newest: {last_time} | Size: {total_mb:.1f} MB"
            if total_mb > 1024:
                summary += f" ({total_mb/1024:.2f} GB)"
        self.video_summary_label.config(text=summary)

    def play_videos(self):
        vid_types = ("*.mp4", "*.mkv", "*.avi")
        files = []
        for vt in vid_types:
            files.extend(glob.glob(os.path.join(self.save_dir, vt)))
        if not files:
            messagebox.showinfo("No Videos Found", "No saved videos found in the directory.")
            return
        try:
            subprocess.Popen(["mpv"] + files)
        except Exception as e:
            messagebox.showerror("Error", f"Could not play videos: {e}")

    def start_motion(self):
        config_path = self.motion_conf_path
        ip = self.config['ip']
        user = self.config['username']
        password = self.config['password']
        rtsp_repl = f'rtsp://{user}:{password}@{ip}:554/Streaming/Channels/101'
        print(f"[DEBUG] Using motion.conf file: {config_path}")
        try:
            with open(config_path) as f:
                text = f.read()
            text = re.sub(
                r'rtsp://[^:@]+:[^@]+@[\d\.]+:554/Streaming/Channels/101',
                rtsp_repl,
                text
            )
            text = re.sub(
                r'rtsp://[^:@]+:[^@]+@[\d\.]+:554',
                f'rtsp://{user}:{password}@{ip}:554',
                text
            )
            with open(config_path, "w") as f:
                f.write(text)
            self.motion_proc = subprocess.Popen(['motion', '-c', config_path])
            print("[DEBUG] Motion started with updated config.")
            self.update_status("Motion running", "blue")
            self.motion_btn.config(state='disabled')
            self.stop_motion_btn.config(state='normal')
            self.update_video_summary()
        except Exception as e:
            print(f"[DEBUG] Failed to start motion: {e}")
            messagebox.showerror("Error", f"Failed to start motion: {e}")

    def stop_motion(self):
        if self.motion_proc is not None:
            print("[DEBUG] Stopping motion process...")
            try:
                self.motion_proc.terminate()
                self.motion_proc.wait(timeout=5)
                print("[DEBUG] Motion process terminated.")
                self.update_status("Motion stopped", "orange")
            except Exception as e:
                print(f"[DEBUG] Error terminating motion: {e}")
                messagebox.showerror("Error", f"Error stopping motion: {e}")
            finally:
                self.motion_proc = None
                self.motion_btn.config(state='normal')
                self.stop_motion_btn.config(state='disabled')
            self.update_video_summary()
        else:
            print("[DEBUG] No running motion process.")

    def move(self, x, y):
        try:
            if not self.ptz or not self.token:
                self.update_status("PTZ not connected", "red")
                messagebox.showerror("Movement Error", "PTZ service not connected.")
                return
            print(f"[DEBUG] Moving: x={x}, y={y}")
            self.ptz.ContinuousMove({
                'ProfileToken': self.token,
                'Velocity': {'PanTilt': {'x': x, 'y': y}}
            })
        except Exception as e:
            self.update_status("Movement Error", "red")
            messagebox.showerror("Error", f"Movement failed: {str(e)}")

    def go_to_center(self):
        try:
            print("[DEBUG] Going to center preset (x=0, y=0)")
            self.ptz.AbsoluteMove({
                'ProfileToken': self.token,
                'Position': {'PanTilt': {'x': 0, 'y': 0}}
            })
            self.update_status(
                "🟢 Streaming RTSP via MPV\n"
                "🎮 Actively controlling movement through:\n"
                "   ONVIF PTZ (Pan-Tilt-Zoom) API\n"
                "🌐 Web UI via MotionEye Local Server\n",
                "#13ad39"
            )
        except Exception as e:
            self.update_status("Connection Error", "red")
            messagebox.showerror("Error", f"Connecting failed: {str(e)}")

    def open_motioneye(self, quiet=False):
        try:
            out = subprocess.run(
                ["systemctl", "is-active", "motioneye.service"],
                capture_output=True, text=True
            )
            if "inactive" in out.stdout or "failed" in out.stdout or out.returncode != 0:
                subprocess.run(["systemctl", "start", "motioneye.service"])
                import time; time.sleep(1)
                out = subprocess.run(
                    ["systemctl", "is-active", "motioneye.service"],
                    capture_output=True, text=True
                )
                if "active" not in out.stdout:
                    if not quiet:
                        messagebox.showwarning(
                            "motionEye not running",
                            "motionEye could not be started automatically. Please run:\n\nsudo systemctl start motioneye.service\n\nThen click the link again."
                        )
                    return
            webbrowser.open(self.motioneye_url)
        except Exception as e:
            if not quiet:
                messagebox.showerror("motionEye", f"Could not check or start motionEye:\n{e}")

    def update_status(self, text, color):
        if self.status_label:
            self.status_label.config(text=text, fg=color)

if __name__ == "__main__":
    print("[DEBUG] Launching PTZCameraControl application...")
    PTZCameraControl()
