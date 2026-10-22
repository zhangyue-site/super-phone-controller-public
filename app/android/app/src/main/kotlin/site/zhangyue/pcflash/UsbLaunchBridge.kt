package site.zhangyue.pcflash

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import org.json.JSONObject

/** Identity only: never open or claim the phone's NCM/HID interfaces. */
object UsbLaunchBridge {
 private lateinit var app: Context
 private val handler=Handler(Looper.getMainLooper())
 private var installed=false
 private var serial: String?=null
 private var session: String?=null
 private var error: String?=null
 private var owner: Any?=null
 private var changed: ((Map<String,Any?>?)->Unit)?=null
 private var lost: ((String)->Unit)?=null
 private val products=setOf(0x4001,0x4005,0x4041,0x4045)
 private fun manager()=app.getSystemService(Context.USB_SERVICE) as UsbManager
 private fun identity(d: UsbDevice): String? {
  if(d.vendorId!=0x303a || d.productId !in products || d.productName!="Epaper Phone Controller") return null
  if(!manager().hasPermission(d))return null
  return try { d.serialNumber?.uppercase()?.takeIf { Regex("[0-9A-F]{12}").matches(it) } } catch(_: Exception){null}
 }
 private fun live(value: String)=manager().deviceList.values.firstOrNull { identity(it)==value }
 fun initialize(context: Context) {
  if(installed)return
  app=context.applicationContext;installed=true
  val receiver=object: BroadcastReceiver() {
   override fun onReceive(context: Context,intent: Intent) {
    val oldSerial=serial?:return
    val oldSession=session?:return
    if(intent.action!=UsbManager.ACTION_USB_DEVICE_DETACHED)return
    // A HID mode switch briefly re-enumerates the same physical device.
    handler.postDelayed({
     if(session==oldSession && serial==oldSerial && live(oldSerial)==null) {
      val old=session;serial=null;session=null;error=null
      if(ScreenShareService.usbOwnerSerial==oldSerial) {
       ScreenShareService.status="控制板已拔出，屏幕共享已停止"
       app.stopService(Intent(app,ScreenShareService::class.java))
      }
      if(old!=null)lost?.invoke(old)
      changed?.invoke(null)
     }
    },1500)
   }
  }
  val filter=IntentFilter(UsbManager.ACTION_USB_DEVICE_DETACHED)
  if(Build.VERSION.SDK_INT>=33)app.registerReceiver(receiver,filter,Context.RECEIVER_NOT_EXPORTED)
  else app.registerReceiver(receiver,filter)
 }
 fun attachOwner(value: Any,onChanged: (Map<String,Any?>?)->Unit,onLost: (String)->Unit) {
  owner=value;changed=onChanged;lost=onLost
 }
 fun detachOwner(value: Any) { if(owner===value){owner=null;changed=null;lost=null} }
 fun accept(intent: Intent?) {
  if(intent?.action!=UsbManager.ACTION_USB_DEVICE_ATTACHED)return
  @Suppress("DEPRECATION") val requested=intent.getParcelableExtra<UsbDevice>(UsbManager.EXTRA_DEVICE)?:return
  val actual=manager().deviceList[requested.deviceName]?:return
  if(actual.vendorId!=0x303a || actual.productId !in products || actual.productName!="Epaper Phone Controller")return
  val value=identity(actual)
  if(value==null) {error="USB设备尚未授权或无法读取序列号，请重新插入并选择本App";changed?.invoke(mapOf("error" to error));return}
  if(serial!=null && serial!=value && live(serial!!)!=null)return
  adopt(value);changed?.invoke(snapshot())
 }
 private fun adopt(value: String) {
  error=null
  if(serial!=value || session==null){serial=value;session="$value:${SystemClock.elapsedRealtimeNanos()}"}
 }
 fun matches(value: String?)=installed && value!=null && value==session && serial?.let { live(it)!=null }==true
 fun serialFor(value: String?): String?=if(matches(value))serial else null
 fun snapshot(): Map<String,Any?>? {
  if(!installed)return null
  if(serial==null) {
   val candidates=manager().deviceList.values.mapNotNull { identity(it) }.distinct()
   if(candidates.size==1)adopt(candidates.single())
  }
  error?.let{return mapOf("error" to it)}
  val value=serial?:return null
  if(live(value)==null)return null
  val out=mutableMapOf<String,Any?>("serial" to value,"session" to session)
  val saved=app.getSharedPreferences("usb-boards",Context.MODE_PRIVATE).getString(value,null)
  try {
   if(saved!=null) {
    val data=JSONObject(saved);val remote=data.getString("remoteId");val device=data.getString("deviceId")
    if(Regex("[0-9A-F]{2}(:[0-9A-F]{2}){5}").matches(remote) && Regex("[A-Za-z0-9_-]{1,64}").matches(device)) {
     out["remoteId"]=remote;out["deviceId"]=device
    }
   }
  } catch(_: Exception) { /* Corrupt bindings require explicit first pairing again. */ }
  return out
 }
 fun forget(value: String?): Boolean {
  if(!matches(value) || ScreenShareService.active)return false
  val key=serial?:return false
  app.getSharedPreferences("usb-boards",Context.MODE_PRIVATE).edit().remove(key).apply()
  changed?.invoke(snapshot());return true
 }
 fun bind(value: String?,remote: String?,device: String?): Boolean {
  if(!matches(value) || remote==null || device==null || !Regex("[0-9A-F]{2}(:[0-9A-F]{2}){5}").matches(remote) || !Regex("[A-Za-z0-9_-]{1,64}").matches(device))return false
  val key=serial?:return false
  app.getSharedPreferences("usb-boards",Context.MODE_PRIVATE).edit().putString(key,JSONObject().put("remoteId",remote).put("deviceId",device).toString()).apply()
  return true
 }
}
