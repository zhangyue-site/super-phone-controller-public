#include "touch.h"
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
static i2c_master_bus_handle_t bus;
static i2c_master_dev_handle_t touch;
i2c_master_bus_handle_t controller_i2c_bus(){return bus;}
bool controller_touch_init(){
 i2c_master_bus_config_t cfg={};cfg.i2c_port=I2C_NUM_0;cfg.sda_io_num=GPIO_NUM_47;cfg.scl_io_num=GPIO_NUM_48;
 cfg.clk_source=I2C_CLK_SRC_DEFAULT;cfg.glitch_ignore_cnt=7;cfg.flags.enable_internal_pullup=true;
 if(i2c_new_master_bus(&cfg,&bus)!=ESP_OK){ESP_LOGE("touch","Shared I2C init failed");return false;}
 gpio_config_t reset={};reset.pin_bit_mask=1ULL<<7;reset.mode=GPIO_MODE_OUTPUT;
 gpio_config(&reset);gpio_set_level(GPIO_NUM_7,1);vTaskDelay(pdMS_TO_TICKS(100));
 gpio_set_level(GPIO_NUM_7,0);vTaskDelay(pdMS_TO_TICKS(100));
 gpio_set_level(GPIO_NUM_7,1);vTaskDelay(pdMS_TO_TICKS(100));
 if(i2c_master_probe(bus,0x38,100)!=ESP_OK){ESP_LOGW("touch","FT6336 absent; physical keys available");return false;}
 i2c_device_config_t dev={};dev.dev_addr_length=I2C_ADDR_BIT_LEN_7;dev.device_address=0x38;dev.scl_speed_hz=400000;
 if(i2c_master_bus_add_device(bus,&dev,&touch)!=ESP_OK)return false;
 ESP_LOGI("touch","FT6336 ready at 0x38; local touchscreen enabled");return true;
}
int controller_touch_read(int &x,int &y){
 if(!touch)return -1;
 uint8_t reg=0x02,data[5];
 if(i2c_master_transmit_receive(touch,&reg,1,data,sizeof(data),30)!=ESP_OK)return -1;
 if((data[0]&0x0f)==0)return 0;
 if((data[0]&0x0f)!=1)return -1;
 x=((data[1]&15)<<8)|data[2];y=((data[3]&15)<<8)|data[4];
 if(x>=200||y>=200)return -1;
 return 1;
}
