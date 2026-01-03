"""
Interface Gráfica (Tkinter) para Monitorização de Frequência Cardíaca via ECG
Comunica com Raspberry Pi Pico 2 W via Serial
"""

import tkinter as tk
from tkinter import ttk, messagebox
import serial
import serial.tools.list_ports
import threading
import time
import numpy as np
import pan_tompkins as pt
from collections import deque
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

HEART_RATE_TIMEOUT = 5  # segundos sem detectar QRS para alerta
MIN_THRESHOLD_BEEP = 0.3 # Limiar mínimo para emitir beep

class ElectricCardiogramGUI:
    def __init__(self, root, fs=250):
        self.root = root
        self.root.title("Monitor de frequencia cardiaca - Pico 2 W")
        self.root.geometry("800x850")
        self.root.resizable(True, True)
        
        #parte das variaveis
        self.serialConnection = None
        self.isConnected = False
        self.ecgValues = []
        
        self.timeBuffer = deque(maxlen=1000)
        self.signalBuffer = deque(maxlen=1000)
        self.qrsTimes = deque(maxlen=50)
        self.bpmBuffer = deque(maxlen=50)
        self.sampleCount = 0
        self.fs = fs  # Frequência de amostragem

        self.detector = pt.PanTompkinsDetector(self.fs)
        self.timeSinceLastQRS = 0
        self.createInterfaceElements()
        self.updateReadings()
        
    def createInterfaceElements(self):
        #Cria os elementos da interface
        connectionFrame = ttk.LabelFrame(self.root, text="Conexão Serial", padding=15)
        connectionFrame.pack(fill="x", padx=15, pady=15)
        
        ttk.Label(connectionFrame, text="Porta:").grid(row=0, column=0, padx=5)
        self.portCombo = ttk.Combobox(connectionFrame, width=20, state="readonly")
        self.portCombo.grid(row=0, column=1, padx=5)
        self.refreshPorts()
        
        ttk.Button(connectionFrame, text="🔄", width=3, command=self.refreshPorts).grid(row=0, column=2, padx=5)

        self.btnConnect = ttk.Button(connectionFrame, text="Conectar", command=self.toggleConnection)
        self.btnConnect.grid(row=0, column=3, padx=5)
        self.statusLabel = ttk.Label(connectionFrame, text="● Desconectado", foreground="red")
        self.statusLabel.grid(row=0, column=4, padx=10)
        
        cardiogramFrame = ttk.LabelFrame(self.root, text="Eletrocardiograma (ECG)", padding=20)
        cardiogramFrame.pack(fill="both", expand=True, padx=15, pady=15)
        
        self.createElectrocardiogramDisplay(cardiogramFrame, "Electrocardiograma", 0, "ecg", "5A5A5A")
        
    def createElectrocardiogramDisplay(self, parent, label, row, key, color):
        #"""Cria um display dos pulsos cardiacos"""
        frame = tk.Frame(parent, bg=color, bd=2, relief="groove")
        frame.pack(fill="x", pady=8)
        
        tk.Label(frame, text=label, font=("Arial", 11, "bold"), 
                 bg=color, fg="white").pack(pady=3)
        
        pulseLabel = tk.Label(frame, text="No pulse detected", 
                              font=("Arial", 28, "bold"), 
                              bg=color, fg="white")
        pulseLabel.pack(pady=8)
        
        # Guarda referência
        setattr(self, f"pulse_label_{key}", pulseLabel)

    def refreshPorts(self):
        #"""Atualiza lista de portas seriais disponíveis"""
        ports = [port.device for port in serial.tools.list_ports.comports()]
        self.portCombo['values'] = ports
        if ports:
            self.portCombo.current(0)
    
    def toggleConnection(self):
        #"""Conecta/desconecta da porta serial"""
        if not self.isConnected:
            self.connectSerial()
        else:
            self.disconnectSerial()
    
    def connectSerial(self):
        #"""Conecta à porta serial"""
        port = self.portCombo.get()
        if not port:
            messagebox.showerror("Erro", "Selecione uma porta serial!")
            return
        
        try:
            self.serialConnection = serial.Serial(port, 115200, timeout=1)
            time.sleep(2)  # Aguarda inicialização
            self.isConnected = True
            self.statusLabel.config(text="● Conectado", foreground="green")
            self.btnConnect.config(text="Desconectar")
            
            # Inicia thread de leitura
            threading.Thread(target=self.readSerial, daemon=True).start()
            
            messagebox.showinfo("Sucesso", f"Conectado a {port}")
            
        except Exception as e:
            messagebox.showerror("Erro de Conexão", str(e))
    
    def disconnectSerial(self):
        #"""Desconecta da porta serial"""
        if self.serialConnection:
            self.serialConnection.close()
        self.isConnected = False
        self.statusLabel.config(text="● Desconectado", foreground="red")
        self.btnConnect.config(text="Conectar")
 
    def readSerial(self):  
        #"""Thread para ler dados da serial"""
        while self.isConnected:
            try:
                if self.serialConnection and self.serialConnection.in_waiting:
                    line = self.serialConnection.readline().decode('utf-8').strip()
                    # Debug: imprime linha recebida
                    if line:
                        return float(line)
                    else:
                        return None
                time.sleep(0.05)  # 50ms
                
            except Exception as e:
                print(f"Erro na leitura: {e}")
                if not self.isConnected:
                    break
    
    def processStream(self, duration=None, callback=None):
        """
        Processa stream contínuo de dados
        
        Args:
            duration: Duração em segundos (None = infinito)
            callback: Função chamada a cada detecção de QRS
        """
        if not self.serialConnection:
            print("Não conectado!")
            return
        
        print("Iniciando processamento...")
        print("Pressione Ctrl+C para parar\n")
        
        start = time.time()
        
        try:
            while True:
                # Verifica duração
                if duration and (time.time() - start) > duration:
                    break
                
                sample = self.readSerial()
                
                if sample is None:
                    continue
                
                # Timestamp atual
                currentTime = self.sampleCount / self.fs
                self.sampleCount += 1
                
                # Buffers para visualização
                self.timeBuffer.append(currentTime)
                self.signalBuffer.append(sample)
                
                # Processa com Pan-Tompkins
                result = self.detector.processSample(sample, currentTime)
                
                # QRS detectado?
                if result['qrsDetected']:
                    self.qrsTimes.append(currentTime)
                    self.timeSinceLastQRS = time.time()
                    
                    if result['bpm']:
                        self.bpmBuffer.append(result['bpm'])
                        
                        print(f"[{currentTime:.2f}s] QRS detectado!")
                        print(f"  BPM: {result['bpm']:.1f}")
                        print(f"  RR: {result['rrInterval']*1000:.0f} ms\n")
                        
                        # Callback customizado
                        if callback:
                            callback(result)
        
        except KeyboardInterrupt:
            print("\nParado pelo usuário")
        
        finally:
            self.printStats()
    
    def printStats(self):
        """Imprime estatísticas finais"""
        stats = self.detector.getHeartRateStats()
        
        if stats:
            print(f"BPM médio:        {stats['mean_bpm']:.1f} ± {stats['std_bpm']:.1f}")
            print(f"BPM mín/máx:      {stats['min_bpm']:.1f} / {stats['max_bpm']:.1f}")
            print(f"RR médio:         {stats['mean_rr']:.0f} ms")
            print(f"SDNN (HRV):       {stats['sdnn']:.1f} ms")
            print(f"RMSSD (HRV):      {stats['rmssd']:.1f} ms")
            print(f"Total de QRS:     {len(self.detector.qrs_peaks)}")
            print("="*50)
    
    def plotRealTime(self):
        """
        Visualização em tempo real com matplotlib
        """
        if not self.serialConnection:
            print("Não conectado!")
            return
        
        # Setup do plot
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
        
        line1, = ax1.plot([], [], 'b-', label='ECG Filtrado')
        qrsScatter = ax1.scatter([], [], c='r', s=100, marker='o', 
                                   label='QRS', zorder=5)
        ax1.set_ylabel('Amplitude')
        ax1.set_title('Sinal ECG com detecção QRS')
        ax1.legend()
        ax1.grid(True)
        
        line2, = ax2.plot([], [], 'g-', linewidth=2)
        ax2.set_xlabel('Tempo (s)')
        ax2.set_ylabel('BPM')
        ax2.set_title('Frequência Cardíaca Instantânea')
        ax2.grid(True)
        ax2.set_ylim(40, 180)
        
        def init():
            ax1.set_xlim(0, 10)
            ax1.set_ylim(-1, 1)
            return line1, qrsScatter, line2
        
        def update(frame):
            # Lê nova amostra
            sample = self.readSerial()
            
            if sample is not None:
                currentTime = self.sampleCount / self.fs
                self.sampleCount += 1
                
                self.timeBuffer.append(currentTime)
                self.signalBuffer.append(sample)
                
                # Processa
                result = self.detector.processSample(sample, currentTime)
                
                if result['qrsDetected']:
                    self.qrsTimes.append(currentTime)
                    if result['bpm']:
                        self.bpmBuffer.append(result['bpm'])
            
            # Atualiza plots
            if len(self.timeBuffer) > 0:
                # ECG
                line1.set_data(list(self.timeBuffer), list(self.signalBuffer))
                
                # QRS markers
                if len(self.qrsTimes) > 0:
                    qrs_t = [t for t in self.qrsTimes 
                            if t >= self.timeBuffer[0]]
                    qrs_y = [0] * len(qrs_t)
                    qrsScatter.set_offsets(np.c_[qrs_t, qrs_y])
                
                # BPM
                if len(self.bpmBuffer) > 0:
                    bpm_times = list(self.qrsTimes)[-len(self.bpmBuffer):]
                    line2.set_data(bpm_times, list(self.bpmBuffer))
                    ax2.set_xlim(max(0, bpm_times[0]-5), bpm_times[-1]+1)
                
                # Ajusta janela de visualização (últimos 10s)
                if self.timeBuffer[-1] > 10:
                    ax1.set_xlim(self.timeBuffer[-1]-10, self.timeBuffer[-1])
            
            return line1, qrsScatter, line2
        
        ani = FuncAnimation(fig, update, init_func=init, 
                           interval=20, blit=True, cache_frame_data=False)
        
        plt.tight_layout()
        plt.show()
        
    def beepOnQRS(self):
        """Emite um beep ao detectar QRS"""
        if (time.time() - self.timeSinceLastQRS) > MIN_THRESHOLD_BEEP:
            print("\a")  
            while (time.time() - self.timeSinceLastQRS) > HEART_RATE_TIMEOUT:
                print("\a")  #Beep simples (pode não funcionar em todos os sistemas)


def main():
    root = tk.Tk()
    app = ElectricCardiogramGUI(root)
    threading.Thread(target=app.beepOnQRS(), daemon=True).start()
    root.mainloop()

if __name__ == "__main__":
    main()
    
