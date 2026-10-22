#include "usb_network.h"
#include "sdkconfig.h"
#if CONFIG_TINYUSB_NET_MODE_NCM
#include <atomic>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_netif_defaults.h"
#include "lwip/ip4_addr.h"
#include "esp_mac.h"
#include "esp_log.h"
#include "tinyusb_net.h"
#include "freertos/semphr.h"

static esp_netif_t *netif;
static SemaphoreHandle_t tx_mutex;
static std::atomic<bool> active(false),desired_link(false),has_ip(false),backend(false);
static bool linked=false,drain_locked=false;
static std::atomic<unsigned> detach_generation(0);
static unsigned handled_generation=0;
static std::atomic<uint32_t> rx_count(0),tx_count(0);
static uint8_t host_mac[6];
#if CONFIG_CONTROLLER_USB_LOCAL
static esp_netif_ip_info_t local_ip;
#endif
static std::atomic<uint32_t> peer_ip(0);
static const char *TAG="usb_network";
static void free_rx(void*,void *buffer){free(buffer);}
static esp_err_t transmit(void*,void *buffer,size_t len){
 if(!active)return ESP_ERR_INVALID_STATE;
 if(xSemaphoreTake(tx_mutex,pdMS_TO_TICKS(120))!=pdTRUE)return ESP_ERR_TIMEOUT;
 esp_err_t ret=active?tinyusb_net_send_sync(buffer,len,nullptr,pdMS_TO_TICKS(100)):ESP_ERR_INVALID_STATE;
 xSemaphoreGive(tx_mutex);
 if(ret==ESP_OK)++tx_count;
 return ret;
}
static esp_err_t receive(void *buffer,uint16_t len,void*){
 if(!netif || !active)return ESP_OK;
 void *copy=malloc(len);if(!copy)return ESP_ERR_NO_MEM;
 memcpy(copy,buffer,len);++rx_count;
 return esp_netif_receive(netif,copy,len,nullptr);
}
static void ip_event(void*,esp_event_base_t,int32_t id,void *data){
 if(id==IP_EVENT_AP_STAIPASSIGNED){
  auto *event=(ip_event_ap_staipassigned_t*)data;
  if(event->esp_netif!=netif || !active || !desired_link)return;
  peer_ip=event->ip.addr;
  ESP_LOGI(TAG,"USB local peer IP=" IPSTR,IP2STR(&event->ip));return;
 }
 if(id==IP_EVENT_ETH_GOT_IP){
  auto *event=(ip_event_got_ip_t*)data;
  if(event->esp_netif!=netif)return;
  if(!desired_link)return;
#if CONFIG_CONTROLLER_USB_LOCAL
  has_ip=false;
#else
  has_ip=true;
#endif
  ESP_LOGI(TAG,"USB DHCP IP=" IPSTR " gateway=" IPSTR,IP2STR(&event->ip_info.ip),IP2STR(&event->ip_info.gw));
 }else if(id==IP_EVENT_ETH_LOST_IP){has_ip=false;backend=false;}
 controller_net_changed();
}
void controller_usb_net_init(){
 tx_mutex=xSemaphoreCreateMutex();assert(tx_mutex);
 uint8_t board_mac[6];ESP_ERROR_CHECK(esp_read_mac(board_mac,ESP_MAC_WIFI_STA));
 board_mac[0]=(board_mac[0]|2)&0xfe;
 memcpy(host_mac,board_mac,6);host_mac[5]^=1;
 esp_netif_inherent_config_t base=ESP_NETIF_INHERENT_DEFAULT_ETH();
#if CONFIG_CONTROLLER_USB_LOCAL
 IP4_ADDR(&local_ip.ip,192,168,77,1);IP4_ADDR(&local_ip.netmask,255,255,255,0);
 base.ip_info=&local_ip;base.flags=(esp_netif_flags_t)((base.flags & ~ESP_NETIF_DHCP_CLIENT)|ESP_NETIF_DHCP_SERVER|ESP_NETIF_FLAG_AUTOUP);
#endif
 base.if_key="usb_ncm";base.if_desc="phone USB network";base.route_prio=120;
 esp_netif_driver_ifconfig_t driver={};driver.handle=(void*)1;
 driver.transmit=transmit;driver.driver_free_rx_buffer=free_rx;
 esp_netif_config_t cfg={};cfg.base=&base;cfg.driver=&driver;cfg.stack=ESP_NETIF_NETSTACK_DEFAULT_ETH;
 netif=esp_netif_new(&cfg);assert(netif);
 ESP_ERROR_CHECK(esp_netif_set_mac(netif,board_mac));
 ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT,IP_EVENT_ETH_GOT_IP,ip_event,nullptr));
 ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT,IP_EVENT_ETH_LOST_IP,ip_event,nullptr));
#if CONFIG_CONTROLLER_USB_LOCAL
 uint8_t offer=0;
 ESP_ERROR_CHECK(esp_netif_dhcps_option(netif,ESP_NETIF_OP_SET,ESP_NETIF_ROUTER_SOLICITATION_ADDRESS,&offer,sizeof(offer)));
 ESP_ERROR_CHECK(esp_netif_dhcps_option(netif,ESP_NETIF_OP_SET,ESP_NETIF_DOMAIN_NAME_SERVER,&offer,sizeof(offer)));
 ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT,IP_EVENT_AP_STAIPASSIGNED,ip_event,nullptr));
 ESP_LOGI(TAG,"USB local-only DHCP server 192.168.77.1; no gateway/DNS; WiFi OFF");
#else
 ESP_LOGI(TAG,"NCM DHCP client ready; WiFi not started");
#endif
}
void controller_usb_net_mac_string(char *out){snprintf(out,13,"%02X%02X%02X%02X%02X%02X",host_mac[0],host_mac[1],host_mac[2],host_mac[3],host_mac[4],host_mac[5]);}
void controller_usb_net_attach(){
 tinyusb_net_config_t cfg={};memcpy(cfg.mac_addr,host_mac,6);cfg.on_recv_callback=receive;
 ESP_ERROR_CHECK(tinyusb_net_init(&cfg));active=true;
}
void controller_usb_net_begin_detach(){
 active=false;desired_link=false;peer_ip=0;has_ip=false;backend=false;++detach_generation;controller_net_changed();
 // Take the TCP/IP interface down and drain in-flight sends while TinyUSB lives.
 controller_usb_net_service();
 if(!drain_locked){xSemaphoreTake(tx_mutex,portMAX_DELAY);drain_locked=true;}
}
void controller_usb_net_detach(){
 // The TinyUSB task must be stopped before this call, so no RX callbacks survive.
 tinyusb_net_deinit();desired_link=false;
 if(drain_locked){drain_locked=false;xSemaphoreGive(tx_mutex);}
}
void controller_usb_net_link(bool up){
 desired_link=up;
 if(!up){peer_ip=0;has_ip=false;backend=false;++detach_generation;}
 controller_net_changed();
}
void controller_usb_net_service(){
 unsigned generation=detach_generation.load();
 if(generation!=handled_generation){
  handled_generation=generation;
  if(linked){esp_netif_action_disconnected(netif,nullptr,0,nullptr);esp_netif_action_stop(netif,nullptr,0,nullptr);linked=false;}
 }
 bool up=active.load()&&desired_link.load();if(up==linked)return;
 linked=up;
 if(up){
#if CONFIG_CONTROLLER_USB_LOCAL
  ESP_LOGI(TAG,"USB host attached; offering local IP only, no internet route");
#else
  ESP_LOGI(TAG,"USB host attached; requesting DHCP from phone sharing");
#endif
  esp_netif_action_start(netif,nullptr,0,nullptr);
  esp_netif_action_connected(netif,nullptr,0,nullptr);
 }else{
  esp_netif_action_disconnected(netif,nullptr,0,nullptr);
  esp_netif_action_stop(netif,nullptr,0,nullptr);
  ESP_LOGI(TAG,"USB host detached");
 }
}
bool controller_usb_net_has_ip(){return has_ip.load();}
int controller_usb_net_stage(){
#if CONFIG_CONTROLLER_USB_LOCAL
 return desired_link?(peer_ip?6:5):1;
#else
 return backend?4:has_ip?3:desired_link?2:1;
#endif
}
uint32_t controller_usb_net_peer(){return peer_ip.load();}
void controller_usb_net_backend(bool ready){if(backend.exchange(ready)!=ready)controller_net_changed();}
void controller_usb_net_counters(uint32_t *rx,uint32_t *tx){*rx=rx_count;*tx=tx_count;}
#else
uint32_t controller_usb_net_peer(){return 0;}
void controller_usb_net_init(){}
void controller_usb_net_attach(){}
void controller_usb_net_mac_string(char *out){out[0]=0;}
void controller_usb_net_begin_detach(){}
void controller_usb_net_detach(){}
void controller_usb_net_link(bool){}
void controller_usb_net_service(){}
bool controller_usb_net_has_ip(){return false;}
int controller_usb_net_stage(){return 0;}
void controller_usb_net_backend(bool){}
void controller_usb_net_counters(uint32_t *rx,uint32_t *tx){*rx=0;*tx=0;}
#endif
