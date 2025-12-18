# main.py no seu Raspberry Pi Pico (MicroPython)
from scipy import signal
import numpy as np
import time
from machine import ADC, Pin

# Configuração do pino de entrada analógica
# Usaremos o ADC 0 (GP26) como exemplo
adc_pin = ADC(Pin(26))

"""
DESIGN DE FILTROS FIR E IIR - Versão Corrigida
Objetivo: Filtro passa-baixo para ECG com especificações rigorosas
"""

# ========== ESPECIFICAÇÕES DO FILTRO ==========
# Frequências importantes
PASSBAND_EDGE = 250     # Hz - Limite da banda de passagem (ECG útil)
STOPBAND_EDGE = 400     # Hz - Início da banda de rejeição (ruído)
TRANSITION_WIDTH = STOPBAND_EDGE - PASSBAND_EDGE  # 30 Hz
CORRECTION_FACTOR = 58 # Hz - ajuste dos valores programados para o FIR

# Atenuações
PASSBAND_RIPPLE = 1     # dB - Máxima variação permitida na passband
STOPBAND_ATTEN = 40     # dB - Mínima atenuação na stopband

# Amostragem
SAMPLING_FREQUENCY = 2e3  # Hz
NYQUIST = SAMPLING_FREQUENCY / 2

# ========== DESIGN FILTRO FIR (Janela de Kaiser) ==========
# Apesar de ser mais exigente computacionalmente que um filtro IIR, por questoes de preservacao
# de informacao do ECG, optamos por um filtro FIR

# Normalizar frequências (0 a 1, onde 1 = Nyquist)
norm_passband = PASSBAND_EDGE / NYQUIST
norm_stopband = STOPBAND_EDGE / NYQUIST
norm_width = TRANSITION_WIDTH / NYQUIST

# Calcular ordem e beta usando kaiserord
# Nota: kaiserord espera atenuação em dB POSITIVO
N_kaiser, beta_kaiser = signal.kaiserord(STOPBAND_ATTEN, norm_width)

# kaiserord pode retornar ordem ímpar, forçar par para simetria
if N_kaiser % 2 == 0:
    N_kaiser += 1

print(f"Parâmetros Kaiser:")
print(f"  Ordem N = {N_kaiser}")
print(f"  Beta = {beta_kaiser:.2f}")
print(f"  Atraso de grupo = {N_kaiser//2} amostras = {(N_kaiser//2)/SAMPLING_FREQUENCY*1000:.2f} ms\n")

# Design do filtro FIR
# IMPORTANTE: cutoff deve estar no MEIO da transição! 
cutoff_fir = (PASSBAND_EDGE + STOPBAND_EDGE - CORRECTION_FACTOR) / 2 # -2*58

fir_coefficients = signal.firwin(
    N_kaiser, 
    cutoff_fir,
    window=('kaiser', beta_kaiser),
    fs=SAMPLING_FREQUENCY
)

print(f"Cutoff real usado: {cutoff_fir:.1f} Hz (meio da transição)\n")

# ========== ANÁLISE DE RESPOSTA EM FREQUÊNCIA ==========
# Calcular respostas
w_fir, h_fir = signal.freqz(fir_coefficients, worN=8192, fs=SAMPLING_FREQUENCY)

# Converter para dB
h_fir_db = 20 * np.log10(np.abs(h_fir) + 1e-10)

# ========== VERIFICAR SE SPECS FORAM ATENDIDAS ==========
def check_specs(w, h_db, passband, stopband, pass_ripple, stop_atten):
    """Verifica se filtro atende especificações"""
    # Verificar passband
    pass_mask = w <= passband
    pass_response = h_db[pass_mask]
    pass_max = np.max(pass_response)
    pass_min = np.min(pass_response)
    pass_ripple_actual = pass_max - pass_min
    
    # Verificar stopband
    stop_mask = w >= stopband
    stop_response = h_db[stop_mask]
    stop_max = np.max(stop_response)
    
    pass_ok = pass_ripple_actual <= pass_ripple
    stop_ok = stop_max <= -stop_atten
    
    return {
        'pass_ripple': pass_ripple_actual,
        'pass_ok': pass_ok,
        'stop_max': stop_max,
        'stop_ok': stop_ok
    }


print("VERIFICACAO RAPIDA DAS ESPECIFICACOES")
fir_check = check_specs(w_fir, h_fir_db, PASSBAND_EDGE, STOPBAND_EDGE, 
                        PASSBAND_RIPPLE, STOPBAND_ATTEN)
print("\nFIR Kaiser:")
print(f"  Ripple na passband: {fir_check['pass_ripple']:.3f} dB {'✓' if fir_check['pass_ok'] else '✗'}")
print(f"    (especificado: < {PASSBAND_RIPPLE} dB)")
print(f"  Máximo na stopband: {fir_check['stop_max']:.1f} dB {'✓' if fir_check['stop_ok'] else '✗'}")
print(f"    (especificado: < {-STOPBAND_ATTEN} dB)")


# ========== TESTE COM SINAL SINTÉTICO ==========
print("TESTE COM SINAL SINTÉTICO")


duration = 1.0
t = np.linspace(0, duration, int(SAMPLING_FREQUENCY * duration), endpoint=False)

# Sinal de teste
signal_50hz = 1.0 * np.sin(2 * np.pi * 50 * t)
signal_200hz = 0.8 * np.sin(2 * np.pi * 200 * t)
signal_400hz = 1.2 * np.sin(2 * np.pi * 400 * t)
signal_1000hz = 1.4 * np.sin(2 * np.pi * 1000 * t)
noise = 0.2 * np.random.randn(len(t))

signal_original = signal_50hz + signal_200hz + signal_400hz + signal_1000hz + noise

# Aplicar filtros
signal_fir = signal.lfilter(fir_coefficients, 1.0, signal_original)


# ========== ANÁLISE FFT DOS SINAIS ==========
print("\n" + "="*60)
print("ANÁLISE FFT - VERIFICAÇÃO DE ATENUAÇÃO")
print("="*60)

def compute_fft_spectrum(signal_data, fs):
    """
    Calcula o espectro de frequência usando FFT.
    
    Passos:
    1. Aplica FFT (Fast Fourier Transform) no sinal
    2. Calcula magnitude (valor absoluto dos coeficientes complexos)
    3. Normaliza pela quantidade de amostras
    4. Converte para dB (escala logarítmica)
    5. Usa rfft (real FFT) para sinais reais - retorna só frequências positivas
    
    Retorna:
    - freqs: vetor de frequências (0 até fs/2)
    - magnitude_db: magnitude em dB
    """
    N = len(signal_data)
    
    # FFT para sinais reais (só frequências positivas)
    fft_result = np.fft.rfft(signal_data)
    
    # Vetor de frequências correspondente
    freqs = np.fft.rfftfreq(N, 1/fs)
    
    # Magnitude normalizada
    magnitude = np.abs(fft_result) / N
    
    # Dobrar magnitude (exceto DC e Nyquist) porque rfft descarta negativas
    magnitude[1:-1] *= 2
    
    # Converter para dB (adiciona pequeno valor para evitar log(0))
    magnitude_db = 20 * np.log10(magnitude + 1e-10)
    
    return freqs, magnitude_db

# Calcular FFT dos três sinais
freqs_orig, fft_orig = compute_fft_spectrum(signal_original, SAMPLING_FREQUENCY)
freqs_fir, fft_fir = compute_fft_spectrum(signal_fir, SAMPLING_FREQUENCY)

# Calcular atenuação real em frequências específicas
test_frequencies = [50, 200, 400, 500, 700, 1000]

print("\nAtenuação medida nos sinais filtrados:")
print("-" * 60)
print(f"{'Freq (Hz)':<12} {'Original (dB)':<15} {'FIR (dB)':<15} {'IIR (dB)':<15}")
print("-" * 60)

for freq_test in test_frequencies:
    # Encontrar índice mais próximo da frequência
    idx = np.argmin(np.abs(freqs_orig - freq_test))
    
    mag_orig = fft_orig[idx]
    mag_fir = fft_fir[idx]
    
    # Atenuação = quanto diminuiu em relação ao original
    atten_fir = mag_fir - mag_orig
    print(f"{freq_test:<12} {mag_orig:<15.2f} {mag_fir:<15.2f} {atten_fir:<15.2f}")



while True:
    # 1. Aquisição de Sinal (Leitura do ADC)
    raw_value = adc_pin.read_u16() # Valor entre 0 e 65535

    
    time.sleep_ms(50) # Taxa de amostragem de ~20Hz