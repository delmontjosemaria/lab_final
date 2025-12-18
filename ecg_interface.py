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
import json

class ElectricCardiogramGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Monitor de frequencia cardiaca - Pico 2 W")
        self.root.geometry("800x850")
        self.root.resizable(True, True)
        
        #parte das variaveis
        self.serialConnection = None
        self.isConnected = False
        self.ecgValues = []
        
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
                        print(f"RX: {line}")
                    
                    # Tenta parsear JSON
                    try:
                        data = dict(json.loads(line))
                        if 'ecg' in data:
                            self.ecgValues.append(data['ecg'])
                            if len(self.ecgValues) > 1000:
                                self.ecgValues.pop(0)
                            
                            # Atualiza display do ECG
                            pulseLabel = getattr(self, "pulse_label_ecg")
                            pulseLabel.config(text=f"{data['ecg']} bpm")
                            
                    except json.JSONDecodeError:
                        # Se não for JSON, pode ser mensagem de debug
                        pass
                
                time.sleep(0.05)  # 50ms
                
            except Exception as e:
                print(f"Erro na leitura: {e}")
                if not self.isConnected:
                    break
    
    def updateReadings(self):
        #Atualiza os displays das leituras atuais
        pass
            

def main():
    root = tk.Tk()
    app = ElectricCardiogramGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
    
