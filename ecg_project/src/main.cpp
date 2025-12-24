#include <Arduino.h>
#include <ringBuffer.h>
#include <Wifi.h>

#define ADC_THRESHOLD_LOW 1998 //ajustavel
#define ADC_THRESHOLD_HIGH 2098 //ajustavel
#define FAST_ACQ_FREQ 250
#define SLEEP_ACQ_FREQ 1
#define MAX_TIMESAMPLE_BUF_SIZE 1000

#define ADC_PIN 26

volatile bool isActiveMode = false;
const int numTaps = 51;
ring_t * rawBuffer = newRing(MAX_TIMESAMPLE_BUF_SIZE);

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


void adcWakeUpHandler(){
  //limpar a máscara de 
  isActiveMode = true;
}

void isrHandler(){
  uint16_t sample = analogRead(ADC_PIN);
  ringPush(rawBuffer, sample);
}

void adcWakeUpHandler();
void isrHandler();

void setup() {
  // put your setup code here, to run once:
}

void loop() {
  // put your main code here, to run repeatedly:
  if(isActiveMode){
    if(isRingFull(rawBuffer)){

    }
  }
  asm volatile ("wfi");
}

