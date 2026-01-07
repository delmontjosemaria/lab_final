#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include "pico/util/queue.h"
#include <pico/multicore.h>
#include <hardware/adc.h>
#include "kiss_fftr.h"
#include <math.h>
#include <credentials.h>

const uint32_t fast_acq_us = 4000;
const uint32_t sleep_acq_us = 1000000;
const uint16_t idle_timeout_ms = 30000;
const int numTaps = 51;
const int adc_threshold_high = 2098; //ajustável
const int max_timesample_buf_size = 1000;
const int max_fft_buf_size = 1024;
const char* topic = "ems/t10/g10";

#define ADC_PIN 26

/*
MQTT Broker subscription ID:
-> ems/t10/g10
Chosen bucket:
-> ems_final_project/ecg_measurement
Chosen measurement
-> estHeartRate
Chosen tags: 
-> samplingRate, source, devs
Chosen fields:
-> BPM
Syntax:
-> mosquitto_pub -t "ems/t10/g10" -m "estHeartRate,samplingRate=250,source=pico2w,devs:delpinho bpm=x" (publicar uma mensagem para um broker)
-> mosquitto_sub -t "ems/t10/g10" (subscrever para um broker)
*/

typedef struct hBuffer{
    size_t capacity;
    size_t size;
    int head;
    int tail;
    uint16_t buffer[max_fft_buf_size];
} hBuffer;

enum State {IDLE, ACTIVE};
volatile State systemState = IDLE;
volatile uint32_t lastActivityTime = 0;
queue_t sampleQueue;
hBuffer historyBuffer;

float fftBuffer[max_fft_buf_size];
int fftBufferIdx = 0;
float bpm;
kiss_fft_cpx fftOut[max_fft_buf_size/2 + 1];
kiss_fftr_cfg cfg = kiss_fftr_alloc(max_fft_buf_size, 0, NULL, NULL);
float fftIn[max_fft_buf_size];
float winFunc[max_fft_buf_size];

WiFiClient ecgClient;
PubSubClient client(ecgClient);

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

void resetActivity();
void core1_entry();
float applyFilter(float newSample);
void setupWiFi();
void reconnectMQTT();
void setupFFTResources();
void setupHistoryBuffer();
void circularWrite(uint16_t value);
void publishBPM(float bpm);
float bpmFunc(float * rawBuffer);

void resetActivity(){
  noInterrupts();
  lastActivityTime = millis();
  interrupts();
}

void core1_entry(){
  uint16_t rawSample;
  float filteredSample;

  while(true){
    queue_remove_blocking(&sampleQueue, &rawSample);
    if (systemState == ACTIVE){
      filteredSample = applyFilter(rawSample);
      Serial.print(filteredSample);
      fftBuffer[fftBufferIdx++] = filteredSample;
      if (fftBufferIdx >= max_fft_buf_size){
        //calcula a fft e guarda em fft
        bpm = bpmFunc(fftBuffer);
        publishBPM(bpm);
        fftBufferIdx = 0;
      }
    }
    else {
      if (rawSample > adc_threshold_high){
        systemState = ACTIVE;
        resetActivity();
      }
    }
  }
}

float applyFilter(float newSample){

  circularWrite(newSample);  
  float output = 0;
  int auxIdx;
  int historyBufferIdx = (historyBuffer.tail - 1 + historyBuffer.capacity) % historyBuffer.capacity;
  
  for (int i = 0; i < numTaps; i++){
    auxIdx = (historyBufferIdx - i + numTaps) % numTaps;
    output += filterCoefs[i] * (float)historyBuffer.buffer[auxIdx];
  }

  return output;
}

void setupWiFi() {
  Serial.print("Conectando ao WiFi");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  
  Serial.println("\nWiFi conectado.");
  Serial.print("IP: ");
  Serial.println(WiFi.localIP());
}

void reconnectMQTT(){
  while(!client.connected()){
    Serial.println("Conectando ao MQTT..."); 

    if(client.connect("ecgClient"))
      Serial.println("Conectado!");
    else{
      Serial.print("Falhou, rc=");
      Serial.println(client.state());
      Serial.println("A tentar novamente em 5 segundos...");
      delay(5000);
    }
  }
}

void setupFFTResources(){
  //hann Window
  for (int i = 0; i < max_fft_buf_size; i++)
    winFunc[i] = 0.5 * (1 - cos(2 * M_PI * i / (max_fft_buf_size - 1)));
}

void setupHistoryBuffer(){
  for (uint16_t pos : historyBuffer.buffer)
   pos = 0;
  historyBuffer.capacity = max_fft_buf_size;
  historyBuffer.size = 0;
  historyBuffer.head = 0;
  historyBuffer.tail = 0;
}

void circularWrite(uint16_t value){
  if(historyBuffer.tail == historyBuffer.head && historyBuffer.size == historyBuffer.capacity)
        historyBuffer.head = ++historyBuffer.head % historyBuffer.capacity;
        //size does not reduce! once it's full, it's forever full

    historyBuffer.buffer[historyBuffer.tail] = value;
    historyBuffer.tail = ++historyBuffer.tail % historyBuffer.capacity;

    if (historyBuffer.size < historyBuffer.capacity)
        historyBuffer.size++;
}

void publishBPM(float bpm){
  if(!client.connected())
    reconnectMQTT();

  char msg[100];
  snprintf(msg, sizeof(msg), "vitals,samplingRate=250,source=pico2w,devs:delpinho estBPM=%.2f", bpm);

  if(client.publish(topic, msg))
    Serial.println("Publicado com sucesso");
  else
    Serial.println("Falha ao publicar");
}

float bpmFunc(float * rawBuffer){
  float bpm;
  float sum = 0;

  for (int i = 0; i < max_fft_buf_size; i++)
    sum += rawBuffer[i];

  float mean = sum / max_fft_buf_size;
  for (int i = 0; i < max_fft_buf_size; i++) {
      // (Sinal - Média) * Janela
      fftIn[i] = (rawBuffer[i] - mean) * winFunc[i];
  }
    // Transforma 'fft_input' (tempo) em 'fft_output' (frequência complexa)
    kiss_fftr(cfg, fftIn, fftOut);

    // Precisamos definir os limites em Índices (Bins) e não em Hz
    // Resolução = Fs / N = 250 / 1024 = 0.244 Hz por bin
    float resolution = (float)(1e6 / fast_acq_us) / max_fft_buf_size;
    
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
    bpm = frequency * 60.0f;
  return bpm;
}

void setup() {
  Serial.begin(115200);

  setupWiFi();
  client.setServer(MQTT_BROKER, MQTT_PORT);

  queue_init(&sampleQueue, sizeof(uint16_t), max_timesample_buf_size);
  lastActivityTime = millis();

  setupHistoryBuffer();
  setupFFTResources();

  multicore_launch_core1(core1_entry);
  Serial.println("Sistema iniciado");
}

void loop() {
  /*
  static uint32_t lastSampleTime = 0;
  uint32_t currentMillis = millis();
  */
  uint32_t currentMicros = micros();

  uint32_t intervalMicros = (systemState == ACTIVE) ? fast_acq_us : sleep_acq_us;

  static uint32_t lastSampleMicros = 0;

  if (currentMicros - lastSampleMicros >= intervalMicros){
    lastSampleMicros = currentMicros;
    uint16_t sample = analogRead(ADC_PIN);

    queue_try_add(&sampleQueue, &sample);
  }

  if(!client.connected())
    reconnectMQTT();

  client.loop();

  if (Serial.available()){
    if (Serial.read() != -1 && systemState == IDLE){
      Serial.println("Activating...");
      systemState = ACTIVE;
    }
    resetActivity();
  }

  if (systemState == ACTIVE){
    if (millis() - lastActivityTime > idle_timeout_ms){
      Serial.println("Entering idle status...");
      systemState = IDLE;
    }
  }
}

