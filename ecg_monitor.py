"""
Interface Gráfica Avançada para Monitorização ECG
Comunicação com Raspberry Pi Pico 2 W via Serial
Com gráficos em tempo real, análise HRV, e detecção de anomalias
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import serial
import serial.tools.list_ports
import threading
import time
import numpy as np
from collections import deque
from datetime import datetime
import json
import paho.mqtt.client as mqtt
import influxdb_client
from influxdb_client.client.write_api import SYNCHRONOUS
import os
from dotenv import load_dotenv

load_dotenv()

# Para gráficos integrados
try:
    import matplotlib
    matplotlib.use('TkAgg')
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    import matplotlib.pyplot as plt
except ImportError:
    print("Aviso: matplotlib não encontrado. Gráficos desabilitados.")

try:
    import pan_tompkins as pt
    PAN_TOMPKINS_AVAILABLE = True
except ImportError:
    PAN_TOMPKINS_AVAILABLE = False
    print("Aviso: módulo pan_tompkins não encontrado. Usaremos simulação simples.")
    
# ============================================================================
# CONFIGURAÇÕES
# ============================================================================

class Config:
    """Configurações globais da aplicação"""
    SAMPLING_RATE = 250  # Hz
    GRAPH_WINDOW = 10    # segundos visíveis no gráfico
    MAX_BUFFER_SIZE = 2500  # 10 segundos @ 250Hz
    
    HEART_RATE_TIMEOUT = 5  # segundos sem QRS = alerta
    CRITICAL_BRADYCARDIA = 40  # BPM
    CRITICAL_TACHYCARDIA = 150  # BPM
    
    # Cores do tema
    COLOR_BG = "#1E1E1E"
    COLOR_FG = "#FFFFFF"
    COLOR_ACCENT = "#0078D4"
    COLOR_SUCCESS = "#28A745"
    COLOR_WARNING = "#FFC107"
    COLOR_DANGER = "#DC3545"
    COLOR_PANEL = "#2D2D2D"

# ============================================================================
# COMPONENTES PERSONALIZADOS
# ============================================================================

class MetricCard(tk.Frame):
    """Card para exibir uma métrica com valor grande e rótulo"""
    
    def __init__(self, parent, title, unit="", color=Config.COLOR_ACCENT, **kwargs):
        super().__init__(parent, bg=Config.COLOR_PANEL, relief="raised", bd=2, **kwargs)
        
        self.color = color
        
        # Título
        self.titleLabel = tk.Label(
            self, 
            text=title, 
            font=("Segoe UI", 10),
            bg=Config.COLOR_PANEL, 
            fg="#AAAAAA"
        )
        self.titleLabel.pack(pady=(10, 5))
        
        # Valor
        self.valueLabel = tk.Label(
            self,
            text="--",
            font=("Segoe UI", 36, "bold"),
            bg=Config.COLOR_PANEL,
            fg=color
        )
        self.valueLabel.pack()
        
        # Unidade
        self.unitLabel = tk.Label(
            self,
            text=unit,
            font=("Segoe UI", 12),
            bg=Config.COLOR_PANEL,
            fg="#AAAAAA"
        )
        self.unitLabel.pack(pady=(0, 10))
    
    def setValue(self, value, unit=None):
        """Atualiza valor do card"""
        if isinstance(value, (int, float)):
            if isinstance(value, float):
                text = f"{value:.1f}"
            else:
                text = str(value)
        else:
            text = str(value)
        
        self.valueLabel.config(text=text)
        
        if unit:
            self.unitLabel.config(text=unit)
    
    def setColor(self, color):
        """Muda cor do valor"""
        self.color = color
        self.valueLabel.config(fg=color)
    
    def flash(self):
        """Efeito de flash no card"""
        originalBg = self.cget("bg")
        self.config(bg=self.color)
        self.after(100, lambda: self.config(bg=originalBg))

class StatusIndicator(tk.Frame):
    """Indicador de status com LED"""
    
    def __init__(self, parent, label, **kwargs):
        super().__init__(parent, bg=Config.COLOR_BG, **kwargs)
        
        # LED (canvas circular)
        self.led = tk.Canvas(self, width=20, height=20, bg=Config.COLOR_BG, 
                            highlightthickness=0)
        self.led.pack(side="left", padx=5)
        self.ledCircle = self.led.create_oval(5, 5, 15, 15, 
                                               fill=Config.COLOR_DANGER, 
                                               outline="")
        
        # Label
        self.label = tk.Label(self, text=label, font=("Segoe UI", 10),
                             bg=Config.COLOR_BG, fg=Config.COLOR_FG)
        self.label.pack(side="left")
    
    def setStatus(self, active, color=None):
        """Define status do LED"""
        if color is None:
            color = Config.COLOR_SUCCESS if active else Config.COLOR_DANGER
        
        self.led.itemconfig(self.ledCircle, fill=color)
    
    def blink(self, times=3, interval=200):
        """Pisca o LED"""
        def toggle(count):
            if count >= times * 2:
                return
            
            currentColor = self.led.itemcget(self.ledCircle, "fill")
            newColor = Config.COLOR_BG if currentColor != Config.COLOR_BG else Config.COLOR_WARNING
            self.led.itemconfig(self.ledCircle, fill=newColor)
            
            self.after(interval, lambda: toggle(count + 1))
        
        toggle(0)


class UserProfileDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.transient(parent)
        self.grab_set()
        self.title("Perfil do Usuário")
        self.geometry("340x320")
        self.resizable(True, True)

        # Will be set when user saves (or {} on cancel)
        self.userData = None

        ttk.Label(self, text="Nome:").pack(pady=5)
        self.entryName = ttk.Entry(self)
        self.entryName.pack(pady=5, fill='x', padx=10)

        ttk.Label(self, text="Idade:").pack(pady=5)
        self.entryAge = ttk.Entry(self)
        self.entryAge.pack(pady=5, fill='x', padx=10)

        ttk.Label(self, text="Peso (kg):").pack(pady=5)
        self.entryWeight = ttk.Entry(self)
        self.entryWeight.pack(pady=5, fill='x', padx=10)

        ttk.Label(self, text="Altura (cm):").pack(pady=5)
        self.entryHeight = ttk.Entry(self)
        self.entryHeight.pack(pady=5, fill='x', padx=10)

        ttk.Label(self, text="Sexo:").pack(pady=5)
        self.sexVar = tk.StringVar(value="M")
        sexFrame = tk.Frame(self)
        sexFrame.pack(pady=5)
        ttk.Radiobutton(sexFrame, text="Masculino", variable=self.sexVar, value="M").pack(side="left", padx=6)
        ttk.Radiobutton(sexFrame, text="Feminino", variable=self.sexVar, value="F").pack(side="left", padx=6)

        btnFrame = tk.Frame(self)
        btnFrame.pack(pady=15)
        ttk.Button(btnFrame, text="Salvar", command=self.saveProfile).pack(side='right', padx=8)
        ttk.Button(btnFrame, text="Cancelar", command=self.cancel).pack(side='left', padx=8)

        self.protocol("WM_DELETE_WINDOW", self.cancel)

        # Make the dialog modal and wait until closed so caller can read `userData`
        parent.wait_window(self)

    def saveProfile(self):
        """Salva os dados do usuário em `self.userData` e fecha o diálogo"""
        name = self.entryName.get().strip()

        # Try to coerce numeric fields; keep None if invalid/empty
        try:
            age = int(self.entryAge.get()) if self.entryAge.get().strip() else None
        except ValueError:
            age = None

        try:
            weight = float(self.entryWeight.get()) if self.entryWeight.get().strip() else None
        except ValueError:
            weight = None

        try:
            height = float(self.entryHeight.get()) if self.entryHeight.get().strip() else None
        except ValueError:
            height = None

        sex = self.sexVar.get()
        # Validate fields and prevent closing if values are absurd.
        issues = []

        if not name:
            issues.append("Nome vazio")

        # Age: prefer 1-120 if provided
        if age is None:
            issues.append("Idade inválida ou vazia")
        else:
            if not (1 <= age <= 120):
                issues.append(f"Idade fora do intervalo razoável: {age}")

        # Weight: prefer 2-500 kg
        if weight is None:
            issues.append("Peso inválido ou vazio")
        else:
            if not (2.0 <= weight <= 500.0):
                issues.append(f"Peso fora do intervalo razoável: {weight}")

        # Height: prefer 30-250 cm
        if height is None:
            issues.append("Altura inválida ou vazia")
        else:
            if not (30.0 <= height <= 250.0):
                issues.append(f"Altura fora do intervalo razoável: {height}")

        if issues:
            # Ask the user what to do: Yes=accept anyway, No=go back and correct, Cancel=discard
            msg = "Os seguintes problemas foram detectados:\n\n"
            msg += "\n".join(f"- {it}" for it in issues)
            msg += "\n\nDeseja aceitar mesmo assim?\n(Yes = Aceitar, No = Corrigir, Cancel = Cancelar sem salvar)"

            answer = messagebox.askyesnocancel("Dados do Perfil - Verificação", msg)
            # True -> accept, False -> correct (do not close), None -> cancel (set empty and close)
            if answer is None:
                self.userData = {}
                self.destroy()
                return
            if answer is False:
                # Let the user correct; do not close
                return

        # If here, either no issues or user accepted anyway
        self.userData = {
            'name': name,
            'age': age,
            'weight': weight,
            'height': height,
            'sex': sex
        }

        self.destroy()

    def cancel(self):
        """User cancelled: set empty dict and close"""
        self.userData = {}
        self.destroy()
        
class ECGMQTTClient:
    """
    MQTT Broker subscription ID with Telegraf for InfluxDB storage:
    -> ems/t10/g10
    Chosen bucket:
    -> ems_final_project/ecg_measurement
    Chosen measurement
    -> healthMetrics
    Chosen tags: 
    -> userName, age, gender, samplingRate, source, devs
    Chosen fields:
    -> bpm, rmssd, calories, stSegDeviation
    Syntax:
    -> mosquitto_pub -t "ems/t10/g10" -m "healthMetrics,userName=JohnDoe,age=25,gender=M,samplingRate=250,source=pico2w,devs:delpinho bpm=x,rmssd=y,calories=z,stSegDeviation=w" (publicar uma mensagem para um broker)
    -> mosquitto_sub -t "ems/t10/g10" (subscrever para um broker)
    """
    
    TOPIC = "ems/t10/g10"
    
    def __init__(self, brokerAddress="localhost", brokerPort=1883):
        self.client = mqtt.Client()
        self.brokerAddress = brokerAddress
        self.brokerPort = brokerPort
        self.isConnected = False
        
    def connect(self):
        try:
            self.client.connect(self.brokerAddress, self.brokerPort)
            self.isConnected = True
            print(f"✓ Conectado ao broker MQTT em {self.brokerAddress}:{self.brokerPort}")
        except Exception as e:
            print(f"✗ Falha ao conectar ao broker MQTT: {e}")
            self.isConnected = False
            
    def publishUserData(self, userProfile:dict, bpm, rmssd, calories, 
                       samplingRate=250, source="pico2w", devs="delpinho"):
        if not self.isConnected:
            print("MQTT não conectado! Não é possível publicar.")
            return False
        
        if not userProfile or not userProfile.get('name'):
            print("Perfil vazio! Não é possível publicar.")
            return False
        
        try:
            content = (
                f"healthMetrics,"
                f"userName={userProfile['name']},"
                f"age={userProfile.get('age', 0)},"
                f"gender={userProfile.get('sex', 'U')},"
                f"samplingRate={samplingRate},"
                f"source={source},"
                f"devs={devs} "
                f"bpm={bpm},"
                f"rmssd={rmssd},"
                f"calories={calories}"
            )
            
            result = self.client.publish(self.TOPIC, content)
            self.client.loop()  
            
            if result.rc == 0:
                print(f"✓ Publicado: {content}")
                return True
            else:
                print(f"✗ Falha na publicação (código {result.rc})")
                return False
                
        except Exception as e:
            print(f"✗ Erro ao publicar: {e}")
            return False
    
    def disconnect(self):
        if self.isConnected:
            self.client.disconnect()
            self.isConnected = False
            print("✓ Desconectado do broker MQTT")
            
    def loop(self):
        """Mantém o loop do cliente MQTT ativo (chamar periodicamente)"""
        if self.isConnected:
            self.client.loop(timeout=1.0)

# ============================================================================
# APLICAÇÃO PRINCIPAL
# ============================================================================

class ModernECGMonitor:
    """Interface gráfica moderna para monitorização ECG"""
    
    def __init__(self, root, userProfile=None):
        self.root = root
        self.root.title("ECG Monitor - Pico 2 W")
        self.root.geometry("1400x900")
        
        # Configuração de estilo
        self.setupStyle()
        
        # Variáveis de estado
        self.serialConnection = None
        self.isConnected = False
        self.isMonitoring = False
        self.isCalibrating = False
        # Allow passing a pre-filled user profile (from the UserProfileDialog)
        self.userProfile = userProfile or {}
        self.caloriesBurned = 0.0
        
        # Buffers de dados
        self.timeBuffer = deque(maxlen=Config.MAX_BUFFER_SIZE)
        self.signalBuffer = deque(maxlen=Config.MAX_BUFFER_SIZE)
        self.qrsTimes = deque(maxlen=100)
        self.bpmBuffer = deque(maxlen=100)
        
        self.sampleCount = 0
        self.lastQRSTime = 0
        
        # Detector Pan-Tompkins (real ou simulado)
        if PAN_TOMPKINS_AVAILABLE:
            self.detector = pt.PanTompkinsDetector(fs=Config.SAMPLING_RATE)
            print("✓ Pan-Tompkins detector inicializado")
        else:
            self.detector = None
            print("⚠ Pan-Tompkins não disponível - usando simulação")
        
        # HRV Calculator (simulado se módulo não disponível)
        self.hrvCalc = None
        
        # Estado atual
        self.currentHR = 0
        self.currentRMSSD = 0
        self.baselineRMSSD = 0
        self.currentState = "Desconhecido"
        
        # Logger
        self.logger = None
        self.sessionActive = False
        
        # Cria interface
        self.createInterface()
        
        # Inicia thread de monitoramento
        self.monitoringThread = None
        self.alertThread = threading.Thread(target=self.alertMonitor, daemon=True)
        self.alertThread.start()
        self.activityThread = threading.Thread(target=self.activityMonitor, daemon=True)
        self.activityThread.start()
    
    def setupStyle(self):
        """Configura tema escuro da aplicação"""
        style = ttk.Style()
        style.theme_use('clam')
        
        # Configurações gerais
        style.configure(".", 
                       background=Config.COLOR_BG,
                       foreground=Config.COLOR_FG,
                       fieldbackground=Config.COLOR_PANEL)
        
        style.configure("TLabel",
                       background=Config.COLOR_BG,
                       foreground=Config.COLOR_FG)
        
        style.configure("TFrame",
                       background=Config.COLOR_BG)
        
        style.configure("TButton",
                       background=Config.COLOR_ACCENT,
                       foreground=Config.COLOR_FG,
                       borderwidth=0,
                       focuscolor='none')
        
        style.map("TButton",
                 background=[('active', Config.COLOR_ACCENT)])
        
        # Root background
        self.root.configure(bg=Config.COLOR_BG)
    
    def createInterface(self):
        """Cria todos os elementos da interface"""
        
        # ====================================================================
        # PAINEL SUPERIOR - Conexão e Controles
        # ====================================================================
        
        topFrame = tk.Frame(self.root, bg=Config.COLOR_PANEL, height=80)
        topFrame.pack(fill="x", padx=10, pady=10)
        topFrame.pack_propagate(False)
        
        # Logo/Título
        titleLabel = tk.Label(
            topFrame,
            text="⚡ ECG Monitor",
            font=("Segoe UI", 18, "bold"),
            bg=Config.COLOR_PANEL,
            fg=Config.COLOR_ACCENT
        )
        titleLabel.pack(side="left", padx=20, pady=20)
        
        # Controles de conexão
        controlsFrame = tk.Frame(topFrame, bg=Config.COLOR_PANEL)
        controlsFrame.pack(side="right", padx=20)
        
        tk.Label(controlsFrame, text="Porta Serial:", bg=Config.COLOR_PANEL,
                fg=Config.COLOR_FG, font=("Segoe UI", 10)).grid(row=0, column=0, padx=5)
        
        self.portCombo = ttk.Combobox(controlsFrame, width=15, state="readonly")
        self.portCombo.grid(row=0, column=1, padx=5)
        # Initial ports refresh will be performed after the log widget
        # is created so that `logEvent()` can safely write to it.
        
        ttk.Button(controlsFrame, text="🔄", width=3,
                  command=self.refreshPort).grid(row=0, column=2, padx=2)
        
        self.btnConnect = ttk.Button(controlsFrame, text="Conectar",
                                      command=self.toggleConnection)
        self.btnConnect.grid(row=0, column=3, padx=5)
        
        self.btnMonitor = ttk.Button(controlsFrame, text="▶ Monitorar",
                                     command=self.toggleMonitoring,
                                     state="disabled")
        self.btnMonitor.grid(row=0, column=4, padx=5)
        
        # Indicadores de status
        statusFrame = tk.Frame(controlsFrame, bg=Config.COLOR_PANEL)
        statusFrame.grid(row=1, column=0, columnspan=5, pady=10)
        
        self.statusConnection = StatusIndicator(statusFrame, "Conexão")
        self.statusConnection.pack(side="left", padx=10)
        
        self.statusMonitoring = StatusIndicator(statusFrame, "Monitoramento")
        self.statusMonitoring.pack(side="left", padx=10)
        
        self.statusHeart = StatusIndicator(statusFrame, "Batimento Cardíaco")
        self.statusHeart.pack(side="left", padx=10)
        
        # ====================================================================
        # PAINEL CENTRAL - Métricas e Gráficos
        # ====================================================================
        
        centralFrame = tk.Frame(self.root, bg=Config.COLOR_BG)
        centralFrame.pack(fill="both", expand=True, padx=10)
        
        # --- COLUNA ESQUERDA: Métricas ---
        metricsFrame = tk.Frame(centralFrame, bg=Config.COLOR_BG, width=300)
        metricsFrame.pack(side="left", fill="y", padx=(0, 10))
        metricsFrame.pack_propagate(False)
        
        # Cards de métricas
        self.cardHR = MetricCard(metricsFrame, "Frequência Cardíaca", "BPM",
                                  color=Config.COLOR_SUCCESS)
        self.cardHR.pack(fill="x", pady=5)
        
        self.cardRMSSD = MetricCard(metricsFrame, "RMSSD (HRV)", "ms",
                                     color=Config.COLOR_ACCENT)
        self.cardRMSSD.pack(fill="x", pady=5)
        
        self.cardState = MetricCard(metricsFrame, "Estado Fisiológico", "",
                                     color=Config.COLOR_WARNING)
        self.cardState.pack(fill="x", pady=5)
        
        # Estatísticas adicionais
        statsLabelFrame = tk.LabelFrame(
            metricsFrame,
            text="Estatísticas da Sessão",
            bg=Config.COLOR_PANEL,
            fg=Config.COLOR_FG,
            font=("Segoe UI", 10, "bold")
        )
        statsLabelFrame.pack(fill="both", expand=True, pady=10)
        
        self.statsText = tk.Text(
            statsLabelFrame,
            height=10,
            bg=Config.COLOR_PANEL,
            fg=Config.COLOR_FG,
            font=("Consolas", 9),
            relief="flat",
            state="disabled"
        )
        self.statsText.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Botões de ação
        actionFrame = tk.Frame(metricsFrame, bg=Config.COLOR_BG)
        actionFrame.pack(fill="x", pady=10)
        
        ttk.Button(actionFrame, text="💾 Salvar Sessão",
                  command=self.saveSession).pack(fill="x", pady=2)
        ttk.Button(actionFrame, text="📊 Relatório",
                  command=self.showReport).pack(fill="x", pady=2)
        ttk.Button(actionFrame, text="⚙️ Configurações",
                  command=self.showSettings).pack(fill="x", pady=2)
        
        # --- COLUNA DIREITA: Gráficos ---
        graphsFrame = tk.Frame(centralFrame, bg=Config.COLOR_PANEL)
        graphsFrame.pack(side="left", fill="both", expand=True)
        
        # Cria figura matplotlib
        self.fig = Figure(figsize=(10, 8), facecolor=Config.COLOR_PANEL)
        
        # Subplot 1: ECG em tempo real
        self.ax_ecg = self.fig.add_subplot(211)
        self.ax_ecg.set_facecolor(Config.COLOR_BG)
        self.ax_ecg.set_title("Sinal ECG", color=Config.COLOR_FG, fontsize=12, pad=10)
        self.ax_ecg.set_ylabel("Amplitude", color=Config.COLOR_FG)
        self.ax_ecg.tick_params(colors=Config.COLOR_FG)
        self.ax_ecg.grid(True, alpha=0.2)
        
        self.line_ecg, = self.ax_ecg.plot([], [], color='#00FF00', linewidth=1.5, 
                                          label='ECG')
        self.scatter_qrs = self.ax_ecg.scatter([], [], color='red', s=100, 
                                              marker='o', zorder=5, label='QRS')
        self.ax_ecg.legend(loc='upper right', facecolor=Config.COLOR_PANEL,
                          edgecolor=Config.COLOR_FG, labelcolor=Config.COLOR_FG)
        
        # Subplot 2: BPM ao longo do tempo
        self.ax_bpm = self.fig.add_subplot(212)
        self.ax_bpm.set_facecolor(Config.COLOR_BG)
        self.ax_bpm.set_title("Frequência Cardíaca", color=Config.COLOR_FG, 
                             fontsize=12, pad=10)
        self.ax_bpm.set_xlabel("Tempo (s)", color=Config.COLOR_FG)
        self.ax_bpm.set_ylabel("BPM", color=Config.COLOR_FG)
        self.ax_bpm.tick_params(colors=Config.COLOR_FG)
        self.ax_bpm.grid(True, alpha=0.2)
        self.ax_bpm.set_ylim(40, 180)
        
        self.line_bpm, = self.ax_bpm.plot([], [], color='#FFD700', linewidth=2, 
                                         marker='o', markersize=4, label='BPM')
        
        # Linhas de referência
        self.ax_bpm.axhline(y=60, color='green', linestyle='--', alpha=0.3, 
                           linewidth=1)
        self.ax_bpm.axhline(y=100, color='orange', linestyle='--', alpha=0.3, 
                           linewidth=1)
        self.ax_bpm.legend(loc='upper right', facecolor=Config.COLOR_PANEL,
                          edgecolor=Config.COLOR_FG, labelcolor=Config.COLOR_FG)
        
        self.fig.tight_layout()
        
        # Integra matplotlib no tkinter
        self.canvas = FigureCanvasTkAgg(self.fig, master=graphsFrame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        
        # ====================================================================
        # PAINEL INFERIOR - Log de Eventos
        # ====================================================================
        
        logFrame = tk.LabelFrame(
            self.root,
            text="Log de Eventos",
            bg=Config.COLOR_PANEL,
            fg=Config.COLOR_FG,
            font=("Segoe UI", 10, "bold")
        )
        logFrame.pack(fill="x", padx=10, pady=(0, 10))
        
        self.logText = scrolledtext.ScrolledText(
            logFrame,
            height=5,
            bg=Config.COLOR_BG,
            fg=Config.COLOR_FG,
            font=("Consolas", 9),
            relief="flat"
        )
        self.logText.pack(fill="both", expand=True, padx=5, pady=5)
        # Now that the log widget exists, populate the port list
        self.refreshPort()
        
        # Inicia atualização da interface
        self.updateInterface()
    
    # ========================================================================
    # CONEXÃO SERIAL
    # ========================================================================
    
    def refreshPort(self):
        """Atualiza lista de portas seriais"""
        ports = [port.device for port in serial.tools.list_ports.comports()]
        self.portCombo['values'] = ports
        if ports:
            self.portCombo.current(0)
        self.logEvent("Portas atualizadas")
    
    def toggleConnection(self):
        """Conecta/desconecta da porta serial"""
        if not self.isConnected:
            self.connectSerial()
        else:
            self.disconnectSerial()
    
    def connectSerial(self):
        """Conecta à porta serial"""
        port = self.portCombo.get()
        if not port:
            messagebox.showerror("Erro", "Selecione uma porta serial!")
            return
        
        try:
            self.serialConnection = serial.Serial(port, 115200, timeout=1)
            time.sleep(2)
            
            self.isConnected = True
            self.statusConnection.setStatus(True)
            self.btnConnect.config(text="Desconectar")
            self.btnMonitor.config(state="normal")
            
            self.logEvent(f"✓ Conectado a {port}", "success")
            
        except Exception as e:
            messagebox.showerror("Erro de Conexão", str(e))
            self.logEvent(f"✗ Erro: {str(e)}", "error")
    
    def disconnectSerial(self):
        """Desconecta da porta serial"""
        if self.isMonitoring:
            self.stopMonitoring()
        
        if self.serialConnection:
            self.serialConnection.close()
        
        self.isConnected = False
        self.statusConnection.setStatus(False)
        self.btnConnect.config(text="Conectar")
        self.btnMonitor.config(state="disabled")
        
        self.logEvent("✓ Desconectado", "info")
    
    # ========================================================================
    # MONITORAMENTO
    # ========================================================================
    
    def toggleMonitoring(self):
        """Inicia/para monitoramento"""
        if not self.isMonitoring:
            self.startMonitoring()
        else:
            self.stopMonitoring()
    
    def startMonitoring(self):
        """Inicia monitoramento"""
        self.isMonitoring = True
        self.statusMonitoring.setStatus(True)
        self.btnMonitor.config(text="⏸ Pausar")
        
        # Realiza calibração inicial de RMSSD
        calibThread = threading.Thread(target=self.calibrateBaselineRMSSD,daemon=True)
        calibThread.start()
        
        # Inicia thread de leitura
        self.monitoringThread = threading.Thread(target=self.readSerial, daemon=True)
        self.monitoringThread.start()
        
        self.logEvent("▶ Monitoramento iniciado", "success")
    
    def stopMonitoring(self):
        """Para monitoramento"""
        self.isMonitoring = False
        self.statusMonitoring.setStatus(False)
        self.btnMonitor.config(text="▶ Monitorar")
        
        self.logEvent("⏸ Monitoramento pausado", "info")
    
    def readSerial(self):
        """Loop de leitura da serial (thread separada)"""
        while self.isMonitoring and self.isConnected:
            try:
                if self.serialConnection and self.serialConnection.in_waiting:
                    line = self.serialConnection.readline().decode('utf-8').strip()
                    
                    if line:
                        try:
                            sample = float(line)
                            self.processSample(sample)
                        except ValueError:
                            pass
                
                time.sleep(0.001)  # 1ms
                
            except Exception as e:
                self.logEvent(f"Erro na leitura: {e}", "error")
                if not self.isConnected:
                    break
    
    def processSample(self, sample):
        """Processa uma amostra ECG"""
        currentTime = self.sampleCount / Config.SAMPLING_RATE
        self.sampleCount += 1
        
        # Adiciona aos buffers
        self.timeBuffer.append(currentTime)
        self.signalBuffer.append(sample)
        
        # Processa com Pan-Tompkins (real ou simulação)
        if self.detector:
            # Usa detector REAL Pan-Tompkins
            result = self.detector.processSample(sample, currentTime)
            
            # Converte formato do resultado
            if result['qrsDetected']:
                result_formatted = {
                    'qrs_detected': True,
                    'bpm': result.get('bpm'),
                    'rr_interval': result.get('rrInterval'),
                    'peak_value': result.get('peakValue')
                }
                self.onQRSDetection(result_formatted, currentTime)
        else:
            # Usa simulação simples
            result = self.simulateDetection(sample, currentTime)
            
            # QRS detectado?
            if result.get('qrs_detected', False):
                self.onQRSDetection(result, currentTime)
            
    def calibrateBaselineRMSSD(self):
        """Consulta ao InfluxDB para baseline RMSSD"""   
        self.isCalibrating = True
        
        if not self.userProfile:
            self.logEvent("⚠ Perfil vazio! Calibrando localmente...", "warning")
            self.localCalibrateRMSSD()
            self.isCalibrating = False
            return

        # Configurações do InfluxDB (usar variáveis de ambiente!)
        bucket = os.getenv('INFLUXDB_BUCKET', 'ems_final_project')
        org = os.getenv('INFLUXDB_ORG', 'ems')
        token = os.getenv('INFLUXDB_TOKEN') 
        url = os.getenv('INFLUXDB_URL', 'http://localhost:8086')
        
        if not token:
            self.logEvent("⚠ Token InfluxDB não configurado! Calibrando localmente...", "warning")
            self.localCalibrateRMSSD()
            self.isCalibrating = False
            return
        
        try:
            client = influxdb_client.InfluxDBClient(
                url=url,
                token=token,
                org=org
            )
            
            queryApi = client.query_api()
            query = f'''
            from(bucket:"{bucket}")
            |> range(start: -10m)
            |> filter(fn:(r) => r._measurement == "healthMetrics")
            |> filter(fn:(r) => r.userName == "{self.userProfile['name']}")
            |> filter(fn:(r) => r._field == "rmssd")
            '''
            
            result = queryApi.query(org=org, query=query)
            results = []
            
            for table in result:
                for record in table.records:
                    results.append(record.get_value())
            
            if results:
                baselineRMSSD = np.mean(results)
                self.baselineRMSSD = baselineRMSSD
                self.logEvent(f"✓ RMSSD do InfluxDB: {baselineRMSSD:.2f} ms", "success")
            else:
                self.logEvent("Sem dados no InfluxDB. Calibrando localmente...", "info")
                self.localCalibrateRMSSD()
            
            client.close()
            
        except Exception as e:
            self.logEvent(f"⚠ Erro InfluxDB: {e}. Calibrando localmente...", "warning")
            self.localCalibrateRMSSD()
        
        self.isCalibrating = False
               
    def localCalibrateRMSSD(self, duration=30):
        """Calibra RMSSD base localmente durante um período de tempo"""
        self.logEvent(
            f"⏳ Calibração local: {duration}s. Mantenha-se quieto...", 
            "info"
        )
        
        rr_intervals = []
        startTime = time.time()
        initialQRSCount = len(self.qrsTimes)
        counter = 0  # ← ADICIONAR contador
        
        while time.time() - startTime < duration:
            # Mensagem visual a cada 5 segundos
            if counter % 50 == 0:  # 50 * 0.1s = 5s
                elapsed = int(time.time() - startTime)
                remaining = duration - elapsed
                self.logEvent(f"⏱ Calibrando... {remaining}s restantes", "info")
            
            # Coleta intervalos RR
            if len(self.qrsTimes) > initialQRSCount:
                if len(self.qrsTimes) >= 2:
                    rr_interval = self.qrsTimes[-1] - self.qrsTimes[-2]
                    rr_intervals.append(rr_interval)
                initialQRSCount = len(self.qrsTimes)
            
            time.sleep(0.1)
            counter += 1  # ← INCREMENTAR contador
        
        # Calcula RMSSD
        if len(rr_intervals) < 2:
            self.logEvent("⚠ Batimentos insuficientes para calibrar.", "warning")
            self.baselineRMSSD = 50  # Valor padrão
            return
        
        rr_diffs = np.diff(rr_intervals)
        squared_diffs = rr_diffs ** 2
        rmssd = np.sqrt(np.mean(squared_diffs)) * 1000  # ms
        
        self.baselineRMSSD = rmssd
        self.logEvent(f"✓ Calibração concluída. RMSSD base: {rmssd:.2f} ms", "success")    
    
    def simulateDetection(self, sample, currentTime):
        """Simulação de detecção (se Pan-Tompkins não disponível)"""
        # Detecta picos simples
        if len(self.signalBuffer) < 3:
            return {'qrs_detected': False}
        
        prev = self.signalBuffer[-2]
        curr = self.signalBuffer[-1]
        
        # Pico local simples
        if curr > 0.5 and curr > prev:
            if len(self.qrsTimes) == 0 or (currentTime - self.qrsTimes[-1]) > 0.4:
                rr_interval = (currentTime - self.qrsTimes[-1]) * 1000 if self.qrsTimes else 800
                bpm = 60000 / rr_interval if rr_interval > 0 else 75
                
                return {
                    'qrs_detected': True,
                    'bpm': bpm,
                    'rr_interval': rr_interval / 1000
                }
        
        return {'qrs_detected': False}
    
    def onQRSDetection(self, result, currentTime):
        """Callback quando QRS é detectado"""
        self.lastQRSTime = time.time()
        self.qrsTimes.append(currentTime)
        
        # Atualiza BPM
        if result.get('bpm'):
            bpm = result['bpm']
            self.currentHR = bpm
            self.bpmBuffer.append(bpm)
            
            # Atualiza card
            self.cardHR.setValue(int(bpm))
            
            # Flash visual
            self.cardHR.flash()
            self.statusHeart.blink(times=1)
            
            # Verifica alertas
            if bpm < Config.CRITICAL_BRADYCARDIA:
                self.cardHR.setColor(Config.COLOR_DANGER)
                self.logEvent(f"⚠ BRADICARDIA CRÍTICA: {bpm:.0f} BPM", "error")
            elif bpm > Config.CRITICAL_TACHYCARDIA:
                self.cardHR.setColor(Config.COLOR_DANGER)
                self.logEvent(f"⚠ TAQUICARDIA CRÍTICA: {bpm:.0f} BPM", "error")
            else:
                self.cardHR.setColor(Config.COLOR_SUCCESS)
    
    # ========================================================================
    # ATUALIZAÇÃO DA INTERFACE
    # ========================================================================
    
    def updateInterface(self):
        """Atualiza gráficos e interface (chamado periodicamente)"""
        if self.isMonitoring and len(self.timeBuffer) > 0:
            # Atualiza gráfico ECG
            times = list(self.timeBuffer)
            signals = list(self.signalBuffer)
            
            self.line_ecg.set_data(times, signals)
            
            # Ajusta limites do eixo X (últimos 10 segundos)
            if times[-1] > Config.GRAPH_WINDOW:
                self.ax_ecg.set_xlim(times[-1] - Config.GRAPH_WINDOW, times[-1])
            else:
                self.ax_ecg.set_xlim(0, Config.GRAPH_WINDOW)
            
            # Ajusta limites do eixo Y
            if len(signals) > 0:
                y_min, y_max = min(signals), max(signals)
                margin = (y_max - y_min) * 0.1
                self.ax_ecg.set_ylim(y_min - margin, y_max + margin)
            
            # Marcadores QRS
            if len(self.qrsTimes) > 0:
                qrsVisible = [t for t in self.qrsTimes if t >= times[0]]
                qrs_y = [0] * len(qrsVisible)
                self.scatter_qrs.set_offsets(np.c_[qrsVisible, qrs_y])
            
            # Atualiza gráfico BPM
            if len(self.bpmBuffer) > 0:
                bpmTimes = list(self.qrsTimes)[-len(self.bpmBuffer):]
                bpmValues = list(self.bpmBuffer)
                self.line_bpm.set_data(bpmTimes, bpmValues)
                
                if len(bpmTimes) > 0:
                    if bpmTimes[-1] > Config.GRAPH_WINDOW:
                        self.ax_bpm.set_xlim(bpmTimes[-1] - Config.GRAPH_WINDOW, 
                                            bpmTimes[-1])
                    else:
                        self.ax_bpm.set_xlim(0, Config.GRAPH_WINDOW)
            
            # Redesenha canvas
            self.canvas.draw_idle()
            
            # Atualiza estatísticas
            self.updateStateStats()
        
        # Reagenda atualização (60 FPS)
        self.root.after(16, self.updateInterface)
    
    def updateStateStats(self):
        """Atualiza painel de estatísticas"""
        if len(self.bpmBuffer) < 2:
            return
        
        bpmArray = np.array(self.bpmBuffer)
        
        # Tenta obter estatísticas do Pan-Tompkins se disponível
        ptStats = None
        if self.detector and hasattr(self.detector, 'getHeartRateStats'):
            ptStats = self.detector.getHeartRateStats()
        
        # Monta texto de estatísticas
        statsText = f"""
            Batimentos detectados: {len(self.qrsTimes)}
            Tempo decorrido: {self.sampleCount/Config.SAMPLING_RATE:.1f}s
            BPM Médio: {np.mean(bpmArray):.1f}
            BPM Mín/Máx: {np.min(bpmArray):.0f} / {np.max(bpmArray):.0f}
            Desvio Padrão: {np.std(bpmArray):.1f}
        """.strip()
        
        # Adiciona estatísticas HRV do Pan-Tompkins se disponível
        if ptStats:
            statsText += f"""

--- Métricas Pan-Tompkins ---
SDNN: {ptStats.get('sdnn', 0):.1f} ms
RMSSD: {ptStats.get('rmssd', 0):.1f} ms
RR Médio: {ptStats.get('mean_rr', 0):.1f} ms
            """
            # Atualiza RMSSD no card
            self.currentRMSSD = ptStats.get('rmssd', 0)
            self.cardRMSSD.setValue(int(self.currentRMSSD))
        else:
            statsText += f"""
RMSSD Atual: {self.currentRMSSD:.1f} ms
            """
        
        statsText += f"\nEstado: {self.currentState}"
        
        self.statsText.config(state="normal")
        self.statsText.delete(1.0, tk.END)
        self.statsText.insert(1.0, statsText.strip())
        self.statsText.config(state="disabled")
    
    # ========================================================================
    # SISTEMA DE ALERTAS
    # ========================================================================
    def keytelEE(self, sex, hr, weight, age, time):
        """Calcula o gasto calórico com base na fórmula de Keytel"""
        if sex == "M":
            return (-55.0969 + (0.6309 * hr) + (0.1988 * weight) + (0.2017 * age)) * time / 4.184
        elif sex == "F":
            return (-20.4022 + (0.4472 * hr) - (0.1263 * weight) + (0.074 * age)) * time / 4.184

    def activityMonitor(self):
        """Thread para monitorar atividade física e calcular gasto calórico"""
        while True:
            try:
                # Verifica se tem perfil
                if not self.userProfile:
                    time.sleep(1)
                    continue
                
                # Verifica se está a monitorar E tem dados válidos
                if (self.isMonitoring and 
                    self.currentRMSSD > 0 and 
                    self.baselineRMSSD > 0):
                    
                    # Critério: RMSSD < 70% do baseline = atividade física
                    if self.currentRMSSD < (0.7 * self.baselineRMSSD):
                        calories = self.keytelEE(
                            self.userProfile['sex'],
                            self.currentHR,
                            self.userProfile['weight'],
                            self.userProfile['age'],
                            60  # 60 segundos
                        )
                        self.caloriesBurned += calories
                        self.logEvent(f"🔥 Gasto calórico: {self.caloriesBurned:.1f} kcal", "info")
                
                time.sleep(60)  # Verifica a cada minuto
                
            except Exception as e:
                self.logEvent(f"Erro em activityMonitor: {e}", "error")
                time.sleep(5)

    def alertMonitor(self):
        """Thread para monitorar alertas críticos"""
        while True:
            if self.isMonitoring and self.lastQRSTime > 0:
                timeSinceQRS = time.time() - self.lastQRSTime
                
                # Alerta de ausência de batimento
                if timeSinceQRS > Config.HEART_RATE_TIMEOUT:
                    self.statusHeart.setStatus(False, Config.COLOR_DANGER)
                    self.logEvent("⚠⚠⚠ SEM BATIMENTO DETECTADO ⚠⚠⚠", "error")
                    
                    # Beep de emergência
                    print("\a")  # Beep do sistema
                else:
                    self.statusHeart.setStatus(True, Config.COLOR_SUCCESS)
            
            time.sleep(1)
    
    # ========================================================================
    # AÇÕES E DIÁLOGOS
    # ========================================================================
    
    def saveSession(self):
        """Salva sessão atual"""
        if len(self.bpmBuffer) == 0:
            messagebox.showinfo("Info", "Nenhum dado para salvar")
            return
        
        publishingClient = ECGMQTTClient()
        publishingClient.connect()
        publishingClient.publishUserData(
            self.userProfile,
            bpm=float(np.mean(self.bpmBuffer)),
            rmssd=self.currentRMSSD,
            calories=self.caloriesBurned,
            samplingRate=Config.SAMPLING_RATE,
            source="pico2w",
            devs="delpinho"
        )
        publishingClient.disconnect()
        try:
            filename = f"sessao_ecg_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            
            data = {
                'timestamp': datetime.now().isoformat(),
                'duration_seconds': self.sampleCount / Config.SAMPLING_RATE,
                'beats_detected': len(self.qrsTimes),
                'bpm_data': list(self.bpmBuffer),
                'stats': {
                    'bpm_mean': float(np.mean(self.bpmBuffer)),
                    'bpm_min': float(np.min(self.bpmBuffer)),
                    'bpm_max': float(np.max(self.bpmBuffer)),
                    'bpm_std': float(np.std(self.bpmBuffer))
                }
            }
            
            with open(filename, 'w') as f:
                json.dump(data, f, indent=2)
            
            messagebox.showinfo("Sucesso", f"Sessão salva: {filename}")
            self.logEvent(f"💾 Sessão salva: {filename}", "success")
        
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao salvar: {e}")
    
    def showReport(self):
        """Mostra janela de relatório"""
        if len(self.bpmBuffer) == 0:
            messagebox.showinfo("Info", "Dados insuficientes para relatório")
            return
        
        # Cria janela de relatório
        reportWindow = tk.Toplevel(self.root)
        reportWindow.title("Relatório da Sessão")
        reportWindow.geometry("600x700")
        reportWindow.configure(bg=Config.COLOR_BG)
        
        # Cabeçalho
        header = tk.Label(
            reportWindow,
            text="📊 Relatório Detalhado",
            font=("Segoe UI", 16, "bold"),
            bg=Config.COLOR_BG,
            fg=Config.COLOR_ACCENT
        )
        header.pack(pady=20)
        
        # Conteúdo
        reportText = scrolledtext.ScrolledText(
            reportWindow,
            bg=Config.COLOR_PANEL,
            fg=Config.COLOR_FG,
            font=("Consolas", 10),
            relief="flat"
        )
        reportText.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Gera relatório
        bpmArray = np.array(self.bpmBuffer)
        
        report_content = f"""
╔══════════════════════════════════════════════════════════╗
║            RELATÓRIO DE MONITORIZAÇÃO ECG                ║
╚══════════════════════════════════════════════════════════╝

Data/Hora: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
Duração: {self.sampleCount/Config.SAMPLING_RATE:.1f} segundos
Taxa de amostragem: {Config.SAMPLING_RATE} Hz

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FREQUÊNCIA CARDÍACA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Total de batimentos: {len(self.qrsTimes)}
BPM Médio: {np.mean(bpmArray):.1f}
BPM Mínimo: {np.min(bpmArray):.0f}
BPM Máximo: {np.max(bpmArray):.0f}
Desvio Padrão: {np.std(bpmArray):.2f}

Percentis:
  P25: {np.percentile(bpmArray, 25):.1f}
  P50 (Mediana): {np.percentile(bpmArray, 50):.1f}
  P75: {np.percentile(bpmArray, 75):.1f}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VARIABILIDADE (HRV)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RMSSD Atual: {self.currentRMSSD:.1f} ms

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OBSERVAÇÕES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Estado fisiológico inferido: {self.currentState}
        """.strip()
        
        reportText.insert(1.0, report_content)
        reportText.config(state="disabled")
        
        # Botão exportar
        ttk.Button(
            reportWindow,
            text="💾 Exportar para TXT",
            command=lambda: self.exportReport(report_content)
        ).pack(pady=10)
    
    def exportReport(self, content):
        """Exporta relatório para arquivo"""
        filename = f"relatorio_ecg_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(content)
            
            messagebox.showinfo("Sucesso", f"Relatório exportado:\n{filename}")
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao exportar: {e}")
    
    def showSettings(self):
        """Mostra janela de configurações"""
        settingsWindow = tk.Toplevel(self.root)
        settingsWindow.title("Configurações")
        settingsWindow.geometry("500x400")
        settingsWindow.configure(bg=Config.COLOR_BG)
        
        tk.Label(
            settingsWindow,
            text="⚙️ Configurações",
            font=("Segoe UI", 16, "bold"),
            bg=Config.COLOR_BG,
            fg=Config.COLOR_ACCENT
        ).pack(pady=20)
        
        tk.Label(
            settingsWindow,
            text="Em desenvolvimento...",
            bg=Config.COLOR_BG,
            fg=Config.COLOR_FG
        ).pack()
    
    # ========================================================================
    # LOG DE EVENTOS
    # ========================================================================
    
    def logEvent(self, message, level="info"):
        """Adiciona evento ao log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Define cor por nível
        colorMap = {
            "info": Config.COLOR_FG,
            "success": Config.COLOR_SUCCESS,
            "warning": Config.COLOR_WARNING,
            "error": Config.COLOR_DANGER
        }
        
        color = colorMap.get(level, Config.COLOR_FG)
        
        # Adiciona ao widget
        self.logText.insert(tk.END, f"[{timestamp}] {message}\n")
        # Do NOT refresh ports from inside the logger (causes recursion)
        
        # Tag de cor
        lineCnt = int(self.logText.index('end-1c').split('.')[0])
        self.logText.tag_add(level, f"{lineCnt}.0", f"{lineCnt}.end")
        self.logText.tag_config(level, foreground=color)
        
        # Auto-scroll
        self.logText.see(tk.END)
        
        # Limita tamanho do log
        if lineCnt > 100:
            self.logText.delete(1.0, 2.0)

# ============================================================================
# MAIN
# ============================================================================

def main():
    root = tk.Tk()
    userInfo = UserProfileDialog(root)
    # Pass the collected user data (userInfo.userData) into the application
    app = ModernECGMonitor(root, userInfo.userData or {})
    root.mainloop()

if __name__ == "__main__":
    main()