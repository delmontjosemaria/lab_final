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
ring_t * rawBuffer = newRing(MAX_TIMESAMPLE_BUF_SIZE);


void adcWakeUpHandler(){
  //limpar a máscara de 
  isActiveMode = true;
}

void isrHandler(){
  uint16_t sample = analogRead(ADC_PIN);
  ringPush(rawBuffer, sample);
}
// put function declarations here:
int myFunction(int, int);

void setup() {
  // put your setup code here, to run once:
  int result = myFunction(2, 3);
}

void loop() {
  // put your main code here, to run repeatedly:
  if(isActiveMode){
    if(isRingFull(rawBuffer))
  }
  asm volatile ("wfi");
}

