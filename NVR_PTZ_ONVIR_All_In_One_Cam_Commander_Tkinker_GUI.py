#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk, messagebox
from onvif import ONVIFCamera
import json
from pathlib import Path
import sys
import subprocess
import re
import webbrowser

class PTZCameraControl:
    def __init__(self):
        print("[DEBUG] Starting PTZCameraControl...")
        self.ip, self.username, self.password = self.get_ip_user_pass()
        print(f"[DEBUG] Selected IP: {self.ip}")
        print(f"[DEBUG] Selected Username: {self.username}")
        self.config = self.load_config()
        print(f"[DEBUG] Loaded config: {self.config}")

        self.root = tk.Tk()
        self.root.title("PTZ Version 13")
        self.root.geometry("360x460")

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
        self.launch_mpv_stream()
        self.root.mainloop()

    def get_ip_user_pass(self):
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
            return ip, user, passwd

        root = tk.Tk()
        root.withdraw()
        ip = None
        user = ""
        passwd = ""

        def on_select():
            nonlocal ip, user, passwd
            ip = combo_ip.get().strip()
            user = entry_user.get().strip()
            passwd = entry_pass.get().strip()
            root.quit()

        prompt = tk.Toplevel(root)
        prompt.title("Select or Enter Camera Details")

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

        tk.Button(prompt, text="OK", command=on_select).grid(row=3, column=0, columnspan=2, pady=8)
        prompt.protocol("WM_DELETE_WINDOW", root.quit)
        root.mainloop()
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

        return ip, user, passwd

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
            btn = tk.Button(
                control_frame,
                text=label,
                width=btn_size//10, height=btn_size//20,
                font=btn_font,
                bg="#ddd",
                relief="raised",
                bd=3,
                command=(lambda x=dx, y=dy, l=label: self.move(x, y) if l != '■' else self.stop())
            )
            btn.grid(row=i//3, column=i%3, padx=2, pady=2, sticky="nsew")
        for i in range(3):
            control_frame.grid_rowconfigure(i, weight=1, minsize=btn_size)
            control_frame.grid_columnconfigure(i, weight=1, minsize=btn_size)

        self.motion_btn = ttk.Button(self.root, text="Start Motion", command=self.start_motion)
        self.motion_btn.pack(pady=8)
        self.stop_motion_btn = ttk.Button(self.root, text="Stop Motion", command=self.stop_motion, state='disabled')
        self.stop_motion_btn.pack(pady=2)

        # Add blue clickable motionEye link at the bottom
        # self.motioneye_url = f"http://{self.ip}:8765"  f"localhost:8765" or 
        self.motioneye_url = f"127.0.0.1:8765"
        link_label = tk.Label(self.root, text=f"Open motionEye: {self.motioneye_url}", fg="blue", cursor="hand2", font=("Helvetica", 11, "underline"))
        link_label.pack(pady=10)
        link_label.bind("<Button-1>", lambda e: self.open_motioneye())

        print("[DEBUG] UI setup complete.")

    def move(self, x, y):
        try:
            print(f"[DEBUG] Moving: x={x}, y={y}")
            self.ptz.ContinuousMove({
                'ProfileToken': self.token,
                'Velocity': {'PanTilt': {'x': x, 'y': y}}
            })
        except Exception as e:
            self.update_status("Movement Error", "red")
            messagebox.showerror("Error", f"Movement failed: {str(e)}")

    def stop(self):
        try:
            print("[DEBUG] Stop PTZ")
            self.ptz.Stop({'ProfileToken': self.token})
            self.update_status("Connected", "green")
        except Exception as e:
            self.update_status("Stop Error", "red")
            messagebox.showerror("Error", f"Stop failed: {str(e)}")

    def start_motion(self):
        config_path = "/home/x/Videos/V380_Motion_Triggered_Vids/motion.conf"
        ip = self.config['ip']
        user = self.config['username']
        password = self.config['password']
        rtsp_repl = f'rtsp://{user}:{password}@{ip}:554/Streaming/Channels/101'
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
        else:
            print("[DEBUG] No running motion process.")

    def open_motioneye(self):
        # Check if motionEye is running
        try:
            # This will work if running as root or with permissions, or use --user for user services
            out = subprocess.run(
                ["systemctl", "is-active", "motioneye.service"],
                capture_output=True, text=True
            )
            if "inactive" in out.stdout or "failed" in out.stdout or out.returncode != 0:
                # Try to start it, might need root!
                started = subprocess.run(
                    ["systemctl", "start", "motioneye.service"]
                )
                # Give it a second to start
                import time; time.sleep(1)
                out = subprocess.run(
                    ["systemctl", "is-active", "motioneye.service"],
                    capture_output=True, text=True
                )
                if "active" not in out.stdout:
                    # Prompt for privilege escalation
                    messagebox.showwarning(
                        "motionEye not running",
                        "motionEye could not be started automatically. Please run:\n\nsudo systemctl start motioneye.service\n\nThen click the link again."
                    )
                    return
            # If running, open browser
            webbrowser.open(self.motioneye_url)
        except Exception as e:
            messagebox.showerror("motionEye", f"Could not check or start motionEye:\n{e}")

    def update_status(self, text, color):
        if self.status_label:
            self.status_label.config(text=text, fg=color)

if __name__ == "__main__":
    print("[DEBUG] Launching PTZCameraControl application...")
    PTZCameraControl()
