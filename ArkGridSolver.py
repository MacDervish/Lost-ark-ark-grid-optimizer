import tkinter as tk
from tkinter import messagebox, filedialog, ttk
import json
import threading
import time
from collections import Counter

# --- SOLVER LOGIC ---
def solve_logic(cores, gems, targets, priorities, callback, timeout=120, stop_check=None):
    num_cores = len(cores)
    gem_fingerprints = []
    for g in gems:
        gem_fingerprints.append((g['wp'], g['pts'], g['eff1'], g['eff1_lvl'], g['eff2'], g['eff2_lvl']))
    
    counts = Counter(gem_fingerprints)
    # Sort by points first (highest points = most valuable for meeting targets)
    distinct_gems = sorted(counts.keys(), key=lambda x: (-x[1], -x[0]))
    gem_types = [(g, counts[g]) for g in distinct_gems]

    best_assignment = None
    max_priority_score = -1
    unique_combinations_count = 0
    combinations_checked = 0
    globally_useful_fingerprints = set()
    
    assignment = [Counter() for _ in range(num_cores)]
    slot_counts, wp_sums, pt_sums = [0]*num_cores, [0]*num_cores, [0]*num_cores
    start_time = time.time()
    last_callback_time = start_time


    def backtrack(type_idx):
        nonlocal best_assignment, max_priority_score, unique_combinations_count, combinations_checked, last_callback_time
        if time.time() - start_time > timeout: return 

        if stop_check and stop_check(): return

        if type_idx == len(gem_types):
            combinations_checked += 1

            #callback once ever 0.1 seconds to reduce computations
            current_time = time.time()
            if current_time - last_callback_time > 0.1:
                callback(unique_combinations_count, None, None, None, progress_update=True, checked=combinations_checked)
                last_callback_time = current_time


            if all(pt_sums[i] >= targets[i] for i in range(num_cores)):
                unique_combinations_count += 1
                current_score = 0
                current_layout = [[] for _ in range(num_cores)]
                
                for i in range(num_cores):
                    for t_idx, count in assignment[i].items():
                        if count > 0:
                            g_data = gem_types[t_idx][0]
                            globally_useful_fingerprints.add(g_data)
                            score_val = (priorities.get(g_data[2], 0) * int(g_data[3]) + 
                                         priorities.get(g_data[4], 0) * int(g_data[5]))
                            current_score += score_val * count
                            for _ in range(count):
                                current_layout[i].append({'wp': g_data[0], 'pts': g_data[1], 'eff1': g_data[2], 'eff1_lvl': g_data[3], 'eff2': g_data[4], 'eff2_lvl': g_data[5]})
                
                if current_score > max_priority_score:
                    max_priority_score = current_score
                    best_assignment = current_layout
            return

        gem_data, available_qty = gem_types[type_idx]
        wp, pts = gem_data[0], gem_data[1]

        #  # OPTIMIZATION: Calculate remaining points potential from future gems
        # remaining_pts_potential = sum(gem_types[j][0][1] * gem_types[j][1] for j in range(type_idx + 1, len(gem_types)))
        
        # # OPTIMIZATION: Early exit if we can't possibly meet targets
        # can_meet_targets = True
        # for i in range(num_cores):
        #     if pt_sums[i] + remaining_pts_potential < targets[i]:
        #         can_meet_targets = False
        #         break
        
        # if not can_meet_targets:
        #     pruned_count = 1
        #     for idx in range(type_idx, len(gem_types)):
        #         _, qty = gem_types[idx]
        #         # Estimate: for each gem type, we have roughly (qty+1)^3 ways to distribute
        #         # This is a rough upper bound
        #         pruned_count *= min((qty+1) ** num_cores, 1000) #cap to prevent overflow
        #         if pruned_count > 1e9: # prevent overflow
        #             pruned_count = int(1e9)
        #             break

        #     combinations_checked += pruned_count

            # #update UI if enough time passed
            # current_time = time.time()
            # if current_time - last_callback_time > 0.1:
            #     callback(unique_combinations_count, None, None, None, progress_update = True, checked = combinations_checked)
            #     last_callback_time = current_time
            # return
        
        # OPTIMIZATION: Calculate max we can place based on both slot and WP constraints
        max_possible = [
            min(available_qty, 4 - slot_counts[i], (cores[i] - wp_sums[i]) // wp if wp > 0 else available_qty)
            for i in range(num_cores)
        ]


        for q0 in range(max_possible[0] + 1):
            remaining_after_0 = available_qty-q0
            for q1 in range(min(max_possible[1], remaining_after_0) + 1):
                remaining_after_1 = remaining_after_0 - q1
                q2_max = min(max_possible[2], remaining_after_1)

                for q2 in range(q2_max+1):
                    qs = [q0, q1, q2]

                    # apply changes
                    for i in range(3):
                        assignment[i][type_idx] = qs[i] 
                        slot_counts[i] += qs[i]
                        wp_sums[i] += qs[i] * wp 
                        pt_sums[i] += qs[i] * pts

                    backtrack(type_idx + 1)

                    # revert changes
                    for i in range(3):
                        slot_counts[i] -= qs[i] 
                        wp_sums[i] -= qs[i] * wp
                        pt_sums[i] -= qs[i] * pts 
                        assignment[i][type_idx] = 0

    backtrack(0)
    callback(unique_combinations_count, best_assignment, max_priority_score, globally_useful_fingerprints, progress_update=False, checked = combinations_checked)

class ArkGridGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Lost Ark: Ark Grid Optimizer")
        self.gems = []
        self.trait_colors = {"Atk Power": "#e68a00", "Brand Power": "#6600cc",  "Boss Dmg": "#b30000", "Ally Atk Enh": "#008000", "Add Dmg": "#0066cc", "Ally Dmg Enh": "#008080"}
        self.colors = {"Ancient": "#FFFACD", "Relic": "#CF0000", "Legendary": "#FFD700", "Epic": "#A335EE"}
        self.effects_list = ["None"] + list(self.trait_colors.keys())
        self.levels_list = ["1", "2", "3", "4", "5"]

        #timer and combo count initialization
        self.start_time = None
        self.timer_running = False
        self.current_combo_count = 0
        self.current_checked_count = 0
        self.stop_requested = False

        # --- CORES ---
        tk.Label(root, text="Step 1: Core Configuration", font=('Arial', 10, 'bold')).grid(row=0, columnspan=4, pady=5)
        self.core_vars, self.target_vars = [tk.IntVar(value=17) for _ in range(3)], [tk.IntVar(value=17) for _ in range(3)]
        self.rarity_buttons, self.target_buttons_dict = [], [{} for _ in range(3)]
        for i, name in enumerate(["Sun Core", "Moon Core", "Star Core"]):
            r_frame = tk.Frame(root); r_frame.grid(row=i*3+3, column=0, columnspan=4, pady=2)
            tk.Label(r_frame, text=f"{name}:", width=10).pack(side="left")
            btns = []
            
            rarities = [("Ancient", 17), ("Relic", 15), ("Legendary", 12), ("Epic", 9)]
            cap_label=tk.Label(root, text="Capacity: ")
            cap_label.grid(row=i*3+5, column=1, sticky= "E")
            for r_n, val in rarities:
                btn = tk.Button(r_frame, text=r_n, bg=self.colors[r_n], width=8, command=lambda n=r_n, v=val, idx=i, lbl=cap_label: self.update_rarity(idx, n, v,lbl))
                
                btn.pack(side="left", padx=2); btns.append(btn)
            self.rarity_buttons.append(btns)
            t_frame = tk.Frame(root); t_frame.grid(row=i*3+4, column=0, columnspan=4)
            tk.Label(t_frame, text="Target:", width=10).pack(side="left")
            for g in [20, 19, 18, 17, 14, 10, 0]:
                btn = tk.Button(t_frame, text=str(g), width=3, command=lambda val=g, idx=i: self.set_target(idx, val))
                btn.pack(side="left", padx=1); self.target_buttons_dict[i][g] = btn
            
            
            self.update_rarity(i, "Relic", 15, cap_label)

            # --- ORDER/CHAOS DROPDOWN ---
        mode_frame = tk.Frame(root)
        mode_frame.grid(row=1, column=0, columnspan=4, pady=5)
        tk.Label(mode_frame, text="Currently Using:", font=('Arial', 9, 'bold')).pack(side="left", padx=5)
        self.gem_mode = tk.StringVar(value="Order Cores")
        mode_dropdown = ttk.Combobox(mode_frame, textvariable=self.gem_mode, values=["Order Cores", "Chaos Cores"], width=15, state="readonly")
        mode_dropdown.pack(side="left", padx=5)

        # --- GEMS ---
        tk.Label(root, text="Step 2: Astrogems", font=('Arial', 10, 'bold')).grid(row=12, columnspan=4, pady=5)
        inp = tk.Frame(root); inp.grid(row=13, column=0, columnspan=4)
        self.gem_wp, self.gem_pts, self.gem_qty = tk.IntVar(value=3), tk.IntVar(value=5), tk.IntVar(value=1)
        for lab, var in [("WP:", self.gem_wp), ("Pts:", self.gem_pts), ("Qty:", self.gem_qty)]:
            tk.Label(inp, text=lab).pack(side="left", padx=2)
            tk.Spinbox(inp, from_=1, to=50, textvariable=var, width=3).pack(side="left", padx=2)
        tk.Button(root, text="Add Gem(s)", command=self.add_gem, bg="#e1e1e1").grid(row=14, column=1, pady=5)
        tk.Button(root, text="Delete Selected", command=self.delete_gem).grid(row=14, column=2, pady=5)

        eff_frame = tk.LabelFrame(root, text="Gem Details (Edit Selected)"); eff_frame.grid(row=15, column=0, columnspan=4, padx=10, pady=5, sticky="ew")
        self.eff1_var, self.eff1_lvl_var = tk.StringVar(value="None"), tk.StringVar(value="1")
        self.eff2_var, self.eff2_lvl_var = tk.StringVar(value="None"), tk.StringVar(value="1")
        self.gem_type_var = tk.StringVar(value="None")

        # Add gem type dropdown at the top
        type_f = tk.Frame(eff_frame); type_f.pack(fill="x", pady=2)
        tk.Label(type_f, text="Gem Type:", font=("Arial", 9, "bold")).pack(side="left", padx=5)
        ttk.Combobox(type_f, textvariable=self.gem_type_var, values=["None", "Order", "Chaos"], width=10, state="readonly").pack(side="left", padx=5)
        tk.Label(type_f, text="(None = wont be used)", font=("Arial", 8, "italic"), fg="gray").pack(side="left")

        for i, (ev, lv) in enumerate([(self.eff1_var, self.eff1_lvl_var), (self.eff2_var, self.eff2_lvl_var)]):
            f = tk.Frame(eff_frame); f.pack(fill="x")
            ttk.Combobox(f, textvariable=ev, values=self.effects_list, width=18, state="readonly").pack(side="left", padx=5)
            ttk.Combobox(f, textvariable=lv, values=self.levels_list, width=3, state="readonly").pack(side="left")
        
        btn_f = tk.Frame(eff_frame); btn_f.pack(fill="x", pady=5)
        tk.Button(btn_f, text="Update Gem", command=self.update_gem).pack(side="left", padx=10)
        tk.Button(btn_f, text="Clear Gem Effects", command=self.clear_gem_eff).pack(side="left")

        tk.Label(root, text="Red = Unused in all combinations", font=('Arial', 9, 'italic'),fg="red").grid(row=17, columnspan=4)

        self.gem_listbox = tk.Listbox(root, height=8, width=75, exportselection=False); self.gem_listbox.grid(row=16, column=0, columnspan=4, pady=5)
        self.gem_listbox.bind('<<ListboxSelect>>', self.on_select)

        # --- SECONDARY STAT WEIGHTING ---
        
        tk.Label(root, text="Step 3: Additional Settings", font=('Arial', 10, 'bold')).grid(row=19, columnspan=4, pady=5)

        timeout_frame = tk.Frame(root)
        timeout_frame.grid(row=20, column=0, columnspan=4, pady=2)
        tk.Label(timeout_frame, text="Max Runtime (seconds):", font=('Arial', 9)).pack(side="left", padx=5)
        self.timeout_var = tk.IntVar(value=120)
        tk.Spinbox(timeout_frame, from_=10, to=28800, textvariable=self.timeout_var, width=6).pack(side="left", padx=5)
        tk.Label(timeout_frame, text="(10-28800s (8 hours), default: 120s)", font=('Arial', 8, 'italic'), fg="gray").pack(side="left")

        tk.Label(root, text="Targets are always met first, these weights will just set which combination is shown", font=('Arial', 8, "italic"),fg="gray").grid(row=21, columnspan=4)

        


        adv_f = tk.LabelFrame(root, text="Scondary stat weights", fg="blue"); adv_f.grid(row=23, column=0, columnspan=4, padx=10, sticky="ew")
        
        # New Legend Label
        tk.Label(adv_f, text="(Scale: 5 = Highest, 0 = Not prioritized)", font=("Arial", 8, "italic"), fg="gray").grid(row=0, column=0, columnspan=4, pady=2)
        
        self.prios = {}
        r, c = 1, 0 # Started traits at row 1 to make room for legend
        for trait in self.trait_colors.keys():
            tk.Label(adv_f, text=trait[:12], font=("Arial", 10)).grid(row=r, column=c, sticky="w")
            v = tk.IntVar(value=0); tk.Spinbox(adv_f, from_=0, to=5, textvariable=v, width=2).grid(row=r, column=c+1, padx=2)
            self.prios[trait] = v
            c += 2
            if c > 3: c = 0; r += 1
        
        # --- FILE MANAGEMENT ---
        
        file_f = tk.Frame(root); file_f.grid(row=18, column=0, columnspan=4, pady=5)
        tk.Button(file_f, text="Sort Gems?", command=self.sort).pack(side="left",padx=5)
        tk.Button(file_f, text="Save Gems", command=self.save_file).pack(side="left", padx=5)
        tk.Button(file_f, text="Load Gems", command=self.load_file).pack(side="left", padx=5)
        tk.Button(file_f, text="Clear All Effects", command=self.clear_all_eff, fg="red").pack(side="left", padx=5)
        tk.Button(file_f, text="Reset All", command=self.reset_all).pack(side="left", padx=5)

        #add a timer widget
        #self.timer_label = tk.Label(root,text = "Time: 0.00s", font=('Arial',10))
        #self.timer_label.grid(row=19, columnspan=4, pady=5)

        #add a widget that shows elapsed time and combinations found
        status_frame = tk.Frame(root)
        status_frame.grid(row=22, columnspan=4, pady=5)
        self.timer_label = tk.Label(status_frame, text="Time: 0.00s", font= ('Arial', 10))
        self.timer_label.pack(side="left", padx=10)
        self.combo_label = tk.Label(status_frame, text="Checked: 0 | Valid: 0", font =('Arial',10))
        self.combo_label.pack(side="left",padx=10)

        #solve button

        self.solve_btn = tk.Button(root, text="SOLVE OPTIMAL GRID", bg="green", fg="white", font=('Arial', 10, 'bold'), command=self.start_solve)
        self.solve_btn.grid(row=24, columnspan=4, pady=10, sticky="ew", padx=20)

        #stop button
        self.stop_btn = tk.Button(root, text="STOP (Shows best found by this point)", bg="red", fg="white", font=('Arial', 10, 'bold'),command=self.stop_solve, state="disabled")
        self.stop_btn.grid(row=25, columnspan=4, pady=5, sticky="ew", padx=20)

    # --- UI HELPER FUNCTIONS ---
    def update_rarity(self, idx, name, val, lbl=None):
        if(lbl != None):
            lbl["text"] ="Capacity: "+str( val)
        self.core_vars[idx].set(val)
        for b in self.rarity_buttons[idx]: b.config(relief="raised")
        [b for b in self.rarity_buttons[idx] if b['text'] == name][0].config(relief="sunken")
        allowed, default = [0, 10, 14, 17, 18, 19, 20], 17
        if name == "Epic": allowed, default = [0, 10], 10
        elif name == "Legendary": allowed, default = [0, 10, 14], 14
        for v, b in self.target_buttons_dict[idx].items():
            b.config(state="normal" if v in allowed else "disabled", bg="#a0a0a0")
        cur = self.target_vars[idx].get()
        self.set_target(idx, default if cur not in allowed or name in ["Ancient", "Relic"] else cur)

    def set_target(self, idx, val):
        self.target_vars[idx].set(val)
        for v, b in self.target_buttons_dict[idx].items():
            if b['state'] == 'normal': b.config(bg="lightgreen" if v == val else "systemButtonFace")

    def add_gem(self):
        for _ in range(self.gem_qty.get()):
            self.gems.insert(0, {'wp': self.gem_wp.get(), 'pts': self.gem_pts.get(), 'eff1': "None", 'eff1_lvl': "1", 'eff2': "None", 'eff2_lvl': "1", 'gem_type': "None"})
        self.refresh_list()

    def update_gem(self):
        s = self.gem_listbox.curselection()
        if s:
            self.gems[s[0]].update({'eff1': self.eff1_var.get(), 'eff1_lvl': self.eff1_lvl_var.get(), 'eff2': self.eff2_var.get(), 'eff2_lvl': self.eff2_lvl_var.get(), 'gem_type': self.gem_type_var.get()})
            self.refresh_list()

    def clear_gem_eff(self):
        s = self.gem_listbox.curselection()
        if s:
            self.gems[s[0]].update({'eff1': "None", 'eff1_lvl': "1", 'eff2': "None", 'eff2_lvl': "1", 'gem_type': "None"})
            self.refresh_list()

    def clear_all_eff(self):
        if messagebox.askyesno("Confirm", "Clear effects from ALL gems?"):
            for g in self.gems: g.update({'eff1': "None", 'eff1_lvl': "1", 'eff2': "None", 'eff2_lvl': "1", 'gem_type':"None"})
            self.refresh_list()

    def delete_gem(self):
        s = self.gem_listbox.curselection()
        if s: self.gems.pop(s[0]); self.refresh_list()

    def reset_all(self):
        if messagebox.askyesno("Reset", "Clear everything?"): self.gems = []; self.refresh_list()

    def refresh_list(self):
        self.gem_listbox.delete(0, tk.END)
        for g in self.gems:
            # adds backwards compatibility cause im lazy
            gem_type= g.get('gem_type', 'None')

            e = f" {g['eff1']} Lv{g['eff1_lvl']}" if g['eff1'] != "None" else " No selection"
            h = f" {g['eff2']} Lv{g['eff2_lvl']}" if g['eff2'] != "None" else " No selection"
            type_tag = f" [{gem_type[0]}]" if gem_type != "None" else ""
            self.gem_listbox.insert(tk.END, f"[{g['wp']}W / {g['pts']}P] {type_tag}      {e}      {h}")

    def sort(self):
        print("sort")
        self.gems = sorted(self.gems, key= lambda x: (x['wp'], -x['pts']))
        self.refresh_list()

    def on_select(self, event):
        s = self.gem_listbox.curselection()
        if s:
            g = self.gems[s[0]]
            self.eff1_var.set(g['eff1']); self.eff1_lvl_var.set(g['eff1_lvl'])
            self.eff2_var.set(g['eff2']); self.eff2_lvl_var.set(g['eff2_lvl'])
            self.gem_type_var.set(g.get('gem_type', 'None'))

    def save_file(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json"), ("Text File", "*.txt")])
        if path:
            with open(path, 'w') as f: json.dump(self.gems, f)

    def load_file(self):
        path = filedialog.askopenfilename(filetypes=[("JSON or Text", "*.json *.txt")])
        if path:
            with open(path, 'r') as f: 
                self.gems = json.load(f)
                for g in self.gems:
                    if 'gem_type' not in g:
                        g['gem_type'] = 'None'

            self.refresh_list()

    def start_solve(self):
        if not self.gems: return

        current_mode = self.gem_mode.get()

        filtered_gems = []
        for g in self.gems:
            gem_type = g.get('gem_type')
            if current_mode == "Order Cores" and gem_type == "Order":
                filtered_gems.append(g)
            elif current_mode == "Chaos Cores" and gem_type == "Chaos":
                filtered_gems.append(g)

        if not filtered_gems:
            messagebox.showerror("Error", f"No gems available for {current_mode}!")
            return


        self.solve_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.stop_requested=False

        self.start_time = time.time()
        self.timer_running = True
        self.current_combo_count = 0
        self.current_checked_count = 0

        #estimates total combinations
        estimated_total = self.calculate_total_combinations(filtered_gems)
        if estimated_total > 1e9:
            total_text = f"{estimated_total/1e9:.1f}e9"
        elif estimated_total > 1e6:
            total_text = f"{estimated_total/1e6:.1f}e6"
        else:
            total_text = f"{estimated_total:,}"

        self.total_estimate = total_text
        self.combo_label.config(text=f"Checked: 0 | Valid: 0")
        self.update_timer()
        p = {k: v.get() for k, v in self.prios.items()}
        timeout = self.timeout_var.get()  
        t = threading.Thread(target=solve_logic, args=([c.get() for c in self.core_vars], list(filtered_gems), [t.get() for t in self.target_vars], p, self.show_res, timeout, lambda: self.stop_requested))
        t.daemon = True; t.start()

    def stop_solve(self):
        """Request Solver to stop and show best solution found"""
        self.stop_requested=True
        self.stop_btn.config(state="disabled")
    

    def show_res(self, count, assign, score, useful_fingerprints, progress_update=False, checked=0):
        self.root.after(0, self._ui_res, count, assign, score, useful_fingerprints, progress_update, checked)

    def _ui_res(self, count, assign, score, useful_fingerprints, progress_update, checked):
        #progress tracking updates
        if progress_update:
            self.current_combo_count=count
            self.current_checked_count=checked

            if checked > 1e9:
                checked_text = f"{checked/1e9:.1f}e9"
            elif checked > 1e6:
                checked_text = f"{checked/1e6:.1f}e6"
            else:
                checked_text = f"{checked:,}"

            self.combo_label.config(text=f"Checked: {checked_text} | Valid: {count}")
            return

        #final results
        self.timer_running = False
        elapsed = time.time() - self.start_time
        self.timer_label.config(text=f"Completed in: {elapsed: .2f}s")

        #format final checked count
        if checked > 1e9:
            checked_text = f"{checked/1e9:.1f}e9"
        elif checked > 1e6:
            checked_text = f"{checked/1e6:.1f}e6"
        else:
            checked_text = f"{checked:,}"

        self.combo_label.config(text=f"Checked: {checked_text} | Valid: {count}")

        self.solve_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

        for idx, g in enumerate(self.gems):
            f = (g['wp'], g['pts'], g['eff1'], g['eff1_lvl'], g['eff2'], g['eff2_lvl'])
            self.gem_listbox.itemconfig(idx, foreground="black" if f in useful_fingerprints else "red")
        if not assign: 
            messagebox.showerror("Error", "No solution reaches targets." + (" (Stopped early)" if self.stop_requested else "")); return
        
        win = tk.Toplevel(self.root); win.title("Optimal Grid Solution" + (" (Stopped early)" if self.stop_requested else ""))
        tk.Label(win, text="Build Summary\n", font=("Arial", 12, "bold")).pack()
        tk.Label(win, text=f"Priority Score: {score} | Valid Combinations: {count}", font=("Arial", 10, "bold")).pack(pady=5)
        main = tk.Frame(win); main.pack(padx=20, pady=10)
        totals = {}
        summary_text = f"BUILD SUMMARY\n"
        for i, name in enumerate(["SUN", "MOON", "STAR"]):
            f = tk.LabelFrame(main, text=name, padx=10, pady=10, labelanchor="n"); f.grid(row=0, column=i, padx=5, sticky="n")
            p_sum = sum(g['pts'] for g in assign[i])
            tk.Label(f, text=f"Total: {p_sum} Pts", fg="green", font=("Arial", 9, "bold")).pack()
            #extract used WP
            wp_sum=0
            for g in assign[i]:
                wp_sum+=g['wp']
            #print(wp_sum)
            tk.Label(f, text=f"WP used: {wp_sum} WP",fg="red", font=("Arial",9,"bold")).pack()
            summary_text += f"\n--- {name} ({p_sum} Pts, {wp_sum} WP used) ---\n"
            for g in assign[i]:
                c = tk.Frame(f, bd=1, relief="solid", bg="white", width=140, height=80)
                c.pack(pady=3); c.pack_propagate(False)
                tk.Label(c, text=f"{g['wp']}W", fg="blue", bg="white", font=("Arial", 7, "bold")).place(x=2, y=2)
                tk.Label(c, text=f"{g['pts']}P", fg="darkgreen", bg="white", font=("Arial", 7, "bold")).place(x=2, y=62)
                gem_desc = f"  [{g['wp']}W/{g['pts']}P]"
                if g['eff1'] != "None":
                    tk.Label(c, text=f"{g['eff1'][:12]} L{g['eff1_lvl']}", bg="white", font=("Arial", 7), fg=self.trait_colors.get(g['eff1'])).place(x=40, y=10)
                    totals[g['eff1']] = totals.get(g['eff1'], 0) + int(g['eff1_lvl'])
                    gem_desc += f" {g['eff1']} L{g['eff1_lvl']}"
                if g['eff2'] != "None":
                    tk.Label(c, text=f"{g['eff2'][:12]} L{g['eff2_lvl']}", bg="white", font=("Arial", 7), fg=self.trait_colors.get(g['eff2'])).place(x=40, y=45)
                    totals[g['eff2']] = totals.get(g['eff2'], 0) + int(g['eff2_lvl'])
                    gem_desc += f" / {g['eff2']} L{g['eff2_lvl']}"
                summary_text += gem_desc + "\n"
        sf = tk.LabelFrame(win, text="Total Levels"); sf.pack(fill="x", padx=20, pady=10)
        summary_text += f"\n   TOTAL LEVELS (Score: {score})\n"

        #define order for displaying effects
        effect_order = ["Atk Power", "Boss Dmg", "Add Dmg", "Brand Power", "Ally Atk Enh", "Ally Dmg Enh"]

        for effect in effect_order:
            if effect in totals:
                v = totals[effect]
                tk.Label(sf, text=f"{effect}: Lvl {v}", fg=self.trait_colors.get(effect), font=("Arial", 9, "bold")).pack(side="left", padx=10)
                summary_text += f"- {effect}: Level {v}\n"
        tk.Button(win, text="Copy Summary to Clipboard", bg="#0052cc", fg="white", command=lambda: self.copy_to_cb(summary_text)).pack(pady=10)

    def copy_to_cb(self, txt):
        self.root.clipboard_clear(); self.root.clipboard_append(txt); messagebox.showinfo("Copied", "Build summary copied!")

    def update_timer(self):
        if self.timer_running:
            elapsed = time.time()-self.start_time
            self.timer_label.config(text=f"Time: {elapsed:.2f}s")
            self.root.after(50, self.update_timer)

    def calculate_total_combinations(self, gems, num_cores=3, max_slots=4):
        """Calculate total possible ways to distribute gems across cores (approximation)"""

        # Count gem quantities
        gem_counts = Counter()
        for g in gems:
            fingerprint = (g['wp'], g['pts'], g['eff1'], g['eff1_lvl'], g['eff2'], g['eff2_lvl'])
            gem_counts[fingerprint] += 1

        total = 1
        for gem_type, quantity in gem_counts.items():
            # Same approximation as pruning: (qty+1)^num_cores ways to distribute
            # This accounts for each core getting 0 to qty of this gem type
            # Cap individual contributions to prevent overflow
            ways = min((quantity + 1) ** num_cores, int(1e9))
            total *= ways
            
            # Prevent total overflow
            if total > 1e12:
                return int(1e12)

        return int(total)


if __name__ == "__main__":
    root = tk.Tk(); ArkGridGUI(root); root.mainloop()