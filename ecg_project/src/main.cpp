#include <Arduino.h>
#include <ringBuffer.h>
#include "kiss_fftr.h"
#include <multicore.h>
#include "pico/util/queue.h"
#include <math.h>
#include <time.h>
#include <timer.h>
#include <Wifi.h>

#define ADC_THRESHOLD_HIGH 2098 //ajustavel
#define FAST_ACQ_US 4000
#define SLEEP_ACQ_US 1000000
#define MAX_TIMESAMPLE_BUF_SIZE 1000
#define MAX_FFT_BUF_SIZE 1024
#define IDLE_TIMEOUT 30000

#define ADC_PIN 26

enum State {IDLE, ACTIVE};
volatile State systemState = IDLE;
volatile uint32_t lastActivityTime = 0;
queue_t sampleQueue;

const int numTaps = 51;
ring_t * historyBuffer = newRing(numTaps);
float fftBuffer[MAX_FFT_BUF_SIZE];
int fftBufferIdx = 0;
float filteredSample;
float rawSample;
float bpm;
kiss_fftr_cfg cfg;
kiss_fft_cpx fftOut[MAX_FFT_BUF_SIZE/2 + 1];;
float fftIn[MAX_FFT_BUF_SIZE];
float winFunc[MAX_FFT_BUF_SIZE];

//Filtro FIR Notch em 50Hz e LowPass em 100Hz. A partir de 125 haveria aliasing, ja
//que a frequencia de amostragem do sinal e de 250Hz. 
float filterCoefs[] = {-1.89763279e-02, -1.40017703e-04,  1.05195952e-02,  2.10976657e-02,
       -8.65483612e-03, -2.84087742e-02, -2.49117352e-03,  1.52279573e-02,
        3.87368715e-02, -2.27039808e-02, -2.93456050e-02, -1.48697579e-02,
        2.85610059e-02,  5.05756958e-02, -3.69880421e-02, -2.09954948e-02,
       -4.17883704e-02,  6.04026308e-02,  3.92400293e-02, -3.52296940e-02,
       -9.74051514e-03, -9.21463580e-02,  1.48872503e-01, -7.96964720e-02,
        1.23622614e-01,  7.95411868e-01,  1.23622614e-01, -7.96964720e-02,
        1.48872503e-01, -9.21463580e-02, -9.74051514e-03, -3.52296940e-02,
        3.92400293e-02,  6.04026308e-02, -4.17883704e-02, -2.09954948e-02,
       -3.69880421e-02,  5.05756958e-02,  2.85610059e-02, -1.48697579e-02,
       -2.93456050e-02, -2.27039808e-02,  3.87368715e-02,  1.52279573e-02,
       -2.49117352e-03, -2.84087742e-02, -8.65483612e-03,  2.10976657e-02,
        1.05195952e-02, -1.40017703e-04, -1.89763279e-02};

void resetActivity(){
  noInterrupts();
  lastActivityTime = millis();
  interrupts();
}

void core1_entry(){
  uint16_t rawSample;

  while(true){
    queue_remove_blocking(&sampleQueue, &rawSample);
    if (systemState == ACTIVE){
      filteredSample = applyFilter(rawSample);
      //envia a amostra para o pc por serial
      fftBuffer[fftBufferIdx++] = filteredSample;
      if (fftBufferIdx >= MAX_FFT_BUF_SIZE){
        //calcula a fft e guarda em fft
        bpm = bpmFunc(fftBuffer);
        //mqtt_publish(vitalsData/bpm, bpm);
        fftBufferIdx = 0;
      }
    }
    else {
      if (rawSample > ADC_THRESHOLD_HIGH){
        systemState = ACTIVE;
        resetActivity();
      }
    }
  }
}

float applyFilter(float newSample){
  float output = 0;
  int historyBufferIdx = 0;
  
  ringPush(historyBuffer, newSample);

  for (int i = 0; i < numTaps; i++){
    historyBufferIdx = (historyBufferIdx - i + numTaps) % numTaps;
    output += filterCoefs[i] * historyBuffer->buffer[historyBufferIdx];
  }

  return output;
}

void setupFFTResources(){
  //hann Window
  for (int i = 0; i < MAX_FFT_BUF_SIZE; i++)
    winFunc[i] = 0.5 * (1 - cos(2 * M_PI * i / (MAX_FFT_BUF_SIZE - 1)));
}

float bpmFunc(float * rawBuffer){
  float bpm;
  cfg = kiss_fftr_alloc(MAX_FFT_BUF_SIZE, 0, NULL, NULL);

  float sum = 0;
  for (int i = 0; i < MAX_FFT_BUF_SIZE; i++)
    sum += rawBuffer[i];

  float mean = sum / MAX_FFT_BUF_SIZE;
  for (int i = 0; i < MAX_FFT_BUF_SIZE; i++) {
      // (Sinal - Média) * Janela
      fftIn[i] = (rawBuffer[i] - mean) * winFunc[i];
  }

    // Transforma 'fft_input' (tempo) em 'fft_output' (frequência complexa)
    kiss_fftr(cfg, fftIn, fftOut);

    // Precisamos definir os limites em Índices (Bins) e não em Hz
    // Resolução = Fs / N = 250 / 1024 = 0.244 Hz por bin
    
    float resolution = (float)(1e6 / FAST_ACQ_US) / MAX_FFT_BUF_SIZE;
    
    // Definir zona de interesse: 40 BPM (0.66 Hz) a 220 BPM (3.66 Hz)
    int minIdx = (int)(0.66 / resolution); 
    int maxIdx = (int)(3.66 / resolution);

    float maxMag = 0;
    int peakIdx = 0;

    // Loop apenas na metade útil (Simetria) e dentro da zona de interesse
    for (int i = minIdx; i <= maxIdx; i++) {    
        float real = fftOut[i].r;
        float imag = fftOut[i].i;
        
        float magnitude = sqrt(real * real + imag * imag);

        if (magnitude > maxMag) {
            maxMag = magnitude;
            peakIdx = i;
        }
    }

    float frequency = peakIdx * resolution;
    float bpm = frequency * 60.0f;
    kiss_fftr_free(cfg);
  return bpm;
}

void setup() {
  Serial.begin(115200);

  queue_init(&sampleQueue, sizeof(uint16_t), MAX_TIMESAMPLE_BUF_SIZE);
  lastActivityTime = millis();

  setupFFTResources();

  multicore_launch_core1(core1_entry);
  Serial.println("Sistema iniciado");
}

void loop() {
  static uint32_t lastSampleTime = 0;
  uint32_t currentMillis = millis();
  uint32_t currentMicros = micros();

  uint32_t intervalMicros = (systemState == ACTIVE) ? FAST_ACQ_US : SLEEP_ACQ_US;

  static uint32_t lastSampleMicros = 0;

  if (currentMicros - lastSampleMicros >= intervalMicros){
    lastSampleMicros = currentMicros;
    uint16_t sample = analogRead(ADC_PIN);

    queue_try_add(&sampleQueue, &sample);
  }

  if (Serial.available()){
    char c = Serial.read();
    if (systemState == IDLE){
      Serial.println("Activating...");
      systemState = ACTIVE;
    }
    resetActivity();
  }

  if (systemState == ACTIVE){
    if (millis() - lastActivityTime > IDLE_TIMEOUT){
      Serial.println("Entering idle status...");
      systemState = IDLE;
    }
  }
}

