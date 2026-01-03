import numpy as np
from collections import deque

class PanTompkinsDetector:
    """
    Implementação do algoritmo Pan-Tompkins para detecção de QRS
    Recebe dados já filtrados do Pico
    """
    def __init__(self, fs=250):
        self.fs = fs
        
        # Parâmetros de janela
        self.mwiSize = int(0.150 * fs)  # 150ms
        
        # Buffers para processamento
        self.derivativeBuffer = deque(maxlen=5)
        self.squaredBuffer = deque(maxlen=self.mwiSize)
        self.mwiBuffer = deque(maxlen=3)  # Para detectar picos locais
             
        # Limiares adaptativos
        self.SPKI = 0  # Signal Peak
        self.NPKI = 0  # Noise Peak
        self.THRESHOLD_I1 = 0
        self.THRESHOLD_I2 = 0
        
        self.SPKF = 0  # Signal Peak (filtered)
        self.NPKF = 0  # Noise Peak (filtered)
        self.THRESHOLD_F1 = 0
        self.THRESHOLD_F2 = 0
        
        # Intervalos RR
        self.rrIntervals = deque(maxlen=8)
        self.rrAverage1 = 0
        self.rrLow = 0
        self.rrHigh = 0
        self.rrMiss = 0
        
        # Detecção de picos
        self.lastQRSTime = 0
        self.qrsPeaks = []
        self.refractoryPeriods = int(0.200 * fs)  # 200ms
        
        # Para análise de slope (onda T)
        self.lastQRSSlope = 0
        
        # Inicialização
        self._initializeThresholds()
    
    def _initializeThresholds(self):
        """Inicializa limiares com valores padrão"""
        self.SPKI = 0.5
        self.NPKI = 0.1
        self.THRESHOLD_I1 = self.NPKI + 0.25 * (self.SPKI - self.NPKI)
        self.THRESHOLD_I2 = 0.5 * self.THRESHOLD_I1
        
        self.SPKF = 0.5
        self.NPKF = 0.1
        self.THRESHOLD_F1 = self.NPKF + 0.25 * (self.SPKF - self.NPKF)
        self.THRESHOLD_F2 = 0.5 * self.THRESHOLD_F1
    
    def derivative(self, sample):
        """
        Operador derivada de 5 pontos
        y(n) = (1/8)[-x(n-2) - 2x(n-1) + 2x(n+1) + x(n+2)]
        """
        self.derivativeBuffer.append(sample)
        
        if len(self.derivativeBuffer) < 5:
            return 0
        
        d = self.derivativeBuffer
        return (-d[0] - 2*d[1] + 2*d[3] + d[4]) / 8.0
    
    def square(self, sample):
        """Elevação ao quadrado"""
        return sample * sample
    
    def movingWindowIntegration(self, sample):
        """
        Integração por janela móvel (MWI)
        y(n) = (1/N)[x(n-(N-1)) + ... + x(n)]
        """
        self.squaredBuffer.append(sample)
        
        if len(self.squaredBuffer) < self.mwiSize:
            return 0
        
        return sum(self.squaredBuffer) / self.mwiSize
    
    def isLocalPeak(self, current_value):
        """Verifica se é um pico local (maior que vizinhos)"""
        self.mwiBuffer.append(current_value)
        
        if len(self.mwiBuffer) < 3:
            return False
        
        # Verifica se o valor do meio é maior que seus vizinhos
        return (self.mwiBuffer[1] > self.mwiBuffer[0] and 
                self.mwiBuffer[1] > self.mwiBuffer[2])
    
    def updateThresholds(self, peakValue, isQRS, filteredPeak=None):
        """Atualiza limiares adaptativos"""
        if isQRS:
            # Atualiza SPKI (Signal Peak)
            self.SPKI = 0.125 * peakValue + 0.875 * self.SPKI
            if filteredPeak is not None:
                self.SPKF = 0.125 * filteredPeak + 0.875 * self.SPKF
        else:
            # Atualiza NPKI (Noise Peak)
            self.NPKI = 0.125 * peakValue + 0.875 * self.NPKI
            if filteredPeak is not None:
                self.NPKF = 0.125 * filteredPeak + 0.875 * self.NPKF
        
        # Recalcula limiares
        self.THRESHOLD_I1 = self.NPKI + 0.25 * (self.SPKI - self.NPKI)
        self.THRESHOLD_I2 = 0.5 * self.THRESHOLD_I1
        
        self.THRESHOLD_F1 = self.NPKF + 0.25 * (self.SPKF - self.NPKF)
        self.THRESHOLD_F2 = 0.5 * self.THRESHOLD_F1
    
    def updateRRIntervals(self, currentTime):
        """Atualiza estatísticas de intervalos RR"""
        if self.lastQRSTime > 0:
            rr = currentTime - self.lastQRSTime
            
            # Verifica se o intervalo é plausível (50-200 BPM)
            if 0.3 < rr < 2.0:  # 0.3s = 200 BPM, 2.0s = 30 BPM
                self.rrIntervals.append(rr)
                
                if len(self.rrIntervals) >= 8:
                    self.rrAverage1 = np.mean(self.rrIntervals)
                    self.rrLow = 0.92 * self.rrAverage1
                    self.rrHigh = 1.16 * self.rrAverage1
                    self.rrMiss = 1.66 * self.rrAverage1
    
    def checkTWave(self, currentSlope):
        """
        Verifica se o pico detectado é uma onda T
        Ondas T têm slope menor que QRS
        """
        if self.lastQRSSlope > 0:
            if currentSlope < 0.5 * self.lastQRSSlope:
                return True  # Provavelmente é onda T
        return False
    
    def searchback(self, currentTime):
        """
        Busca retroativa quando passa muito tempo sem detectar QRS
        Procura picos que superem THRESHOLD_I2 (mais permissivo)
        """
        # Implementação simplificada - em produção, guardaria histórico
        pass
    
    def processSample(self, filteredSample, currentTime):
        """
        Processa uma amostra e retorna se detectou QRS
        
        Args:
            filteredSample: Amostra já filtrada pelo Pico (5-100 Hz)
            currentTime: Timestamp da amostra (segundos)
        
        Returns:
            dict: {'qrsDetected': bool, 'rrInterval': float, 'bpm': float}
        """
        result = {
            'qrsDetected': False,
            'rrInterval': None,
            'bpm': None,
            'peakValue': None
        }
        
        # Pipeline Pan-Tompkins
        deriv = self.derivative(filteredSample)
        squared = self.square(deriv)
        mwi = self.movingWindowIntegration(squared)
        
        # Verifica se é pico local
        if not self.isLocalPeak(mwi):
            return result
        
        peakValue = self.mwiBuffer[1]  # Valor do pico
        
        # Período refratário (não pode ter QRS muito próximos)
        timeSinceLastQRS = currentTime - self.lastQRSTime
        if timeSinceLastQRS < (self.refractoryPeriods / self.fs):
            self.updateThresholds(peakValue, isQRS=False)
            return result
        
        # Decisão: é QRS ou ruído?
        if peakValue > self.THRESHOLD_I1:
            # Candidato a QRS - verifica onda T
            currentSlope = abs(deriv)
            
            if not self.checkTWave(currentSlope):
                # QRS confirmado!
                self.updateThresholds(peakValue, isQRS=True, filteredPeak=filteredSample)
                
                # Atualiza intervalos RR
                if self.lastQRSTime > 0:
                    rrInterval = currentTime - self.lastQRSTime
                    self.updateRRIntervals(currentTime)
                    
                    result['rrInterval'] = rrInterval
                    result['bpm'] = 60.0 / rrInterval if rrInterval > 0 else 0
                
                self.lastQRSTime = currentTime
                self.lastQRSSlope = currentSlope
                self.qrsPeaks.append(currentTime)
                
                result['qrsDetected'] = True
                result['peakValue'] = peakValue
        else:
            # Ruído
            self.updateThresholds(peakValue, isQRS=False)
        
        # searchback se passou muito tempo sem QRS
        if (self.rrMiss > 0 and 
            timeSinceLastQRS > self.rrMiss):
            self.searchback(currentTime)
        
        return result
    
    def getHeartRateStats(self):
        """Retorna estatísticas de frequência cardíaca"""
        if len(self.rrIntervals) < 2:
            return None
        
        rrArray = np.array(self.rrIntervals)
        bpmArray = 60.0 / rrArray
        
        return {
            'mean_bpm': np.mean(bpmArray),
            'std_bpm': np.std(bpmArray),
            'min_bpm': np.min(bpmArray),
            'max_bpm': np.max(bpmArray),
            'mean_rr': np.mean(rrArray) * 1000,  # ms
            'sdnn': np.std(rrArray) * 1000,  # HRV metric (ms)
            'rmssd': np.sqrt(np.mean(np.diff(rrArray)**2)) * 1000  # HRV
        }