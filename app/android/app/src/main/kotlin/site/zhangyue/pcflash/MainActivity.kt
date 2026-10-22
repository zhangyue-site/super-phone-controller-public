package site.zhangyue.pcflash

import android.app.Activity
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.media.projection.MediaProjectionConfig
import android.net.Uri
import android.os.Build
import android.os.Bundle
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity: FlutterActivity() {
 private var pending: MethodChannel.Result? = null
 private var ticket: String? = null
 private var pendingUsbSession: String? = null
 private var consentInFlight=false
 private var pendingRequestCode=-1
 private fun nextConsentCode(): Int {
  val prefs=getSharedPreferences("usb-boards",MODE_PRIVATE)
  val code=prefs.getInt("__consent-code",1000).coerceIn(1000,65000)
  if(!prefs.edit().putInt("__consent-code",if(code>=65000)1000 else code+1).commit())throw IllegalStateException("无法保存授权会话")
  return code
 }
 override fun onCreate(savedInstanceState: Bundle?) {
  super.onCreate(savedInstanceState)
  UsbLaunchBridge.accept(intent)
 }
 override fun onNewIntent(intent: Intent) {
  super.onNewIntent(intent);setIntent(intent);UsbLaunchBridge.accept(intent)
 }
 private fun cancelUsbConsent(value: String) {
  if(pendingUsbSession!=value)return
  ticket?.let { ScreenShareService.revoke(it) };ticket=null;pendingUsbSession=null
  pending?.error("usb_detached","控制板已拔出，请重新插入后共享",null);pending=null
  // Keep consentInFlight until its result arrives; never hand an old result to a new request.
 }

 override fun configureFlutterEngine(engine: FlutterEngine) {
  super.configureFlutterEngine(engine)
  UsbLaunchBridge.initialize(this)
  val usb=MethodChannel(engine.dartExecutor.binaryMessenger,"pcflash/usb")
  UsbLaunchBridge.attachOwner(this,{ usb.invokeMethod("changed",it) },{ cancelUsbConsent(it) })
  usb.setMethodCallHandler { call,result ->
   when(call.method) {
    "snapshot" -> result.success(UsbLaunchBridge.snapshot())
    "bind" -> if(UsbLaunchBridge.bind(call.argument("session"),call.argument("remoteId"),call.argument("deviceId")))result.success(null) else result.error("usb_detached","USB连接已改变，未保存配对",null)
    "forget" -> if(UsbLaunchBridge.forget(call.argument("session")))result.success(null) else result.error("busy","请先停止共享并保持USB连接后重新配对",null)
    else -> result.notImplemented()
   }
  }
  MethodChannel(engine.dartExecutor.binaryMessenger, "pcflash/app").setMethodCallHandler { call, result ->
   when(call.method) {
    "info" -> {
     @Suppress("DEPRECATION")
     val info=packageManager.getPackageInfo(packageName,0)
     @Suppress("DEPRECATION")
     val code=if(Build.VERSION.SDK_INT>=28) info.longVersionCode else info.versionCode.toLong()
     result.success(mapOf("versionName" to info.versionName, "versionCode" to code))
    }
    "openDownload" -> {
     try {
      startActivity(Intent(Intent.ACTION_VIEW,Uri.parse("https://d.zhangyue.site/apps/phone-controller-flash/")))
      result.success(null)
     } catch(_: Exception) { result.error("browser_unavailable","无法打开官方下载页",null) }
    }
    else -> result.notImplemented()
   }
  }
  MethodChannel(engine.dartExecutor.binaryMessenger, "pcflash/screen").setMethodCallHandler { call, result ->
   when(call.method) {
    "start" -> {
     val value=call.argument<String>("ticket")
     val requestedUsb=call.argument<String>("usbSession")
     if(consentInFlight || pending!=null || ScreenShareService.active || value==null || !Regex("[A-Za-z0-9_-]{43}").matches(value)) {
      result.error("busy", "共享正在准备或凭证无效", null)
     } else if(requestedUsb!=null && !UsbLaunchBridge.matches(requestedUsb)) {
      ScreenShareService.revoke(value);result.error("usb_detached","控制板已拔出，请重新插入",null)
     } else {
      pending=result;ticket=value;pendingUsbSession=requestedUsb;consentInFlight=true
      val manager=getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
      try {
       val consent = if(Build.VERSION.SDK_INT>=34) manager.createScreenCaptureIntent(MediaProjectionConfig.createConfigForDefaultDisplay()) else manager.createScreenCaptureIntent()
       pendingRequestCode=nextConsentCode()
       startActivityForResult(consent, pendingRequestCode)
      } catch(_: Exception) {
       pending=null;ticket=null;pendingUsbSession=null;consentInFlight=false;ScreenShareService.revoke(value)
       result.error("permission_failed", "无法请求屏幕共享，请重新开启", null)
      }
     }
    }
    "stop" -> { pendingUsbSession=null;ticket?.let { ScreenShareService.revoke(it) };ticket=null;pending?.error("cancelled","已取消屏幕共享",null);pending=null;ScreenShareService.status="已停止共享";ScreenShareService.taskStatus=""; stopService(Intent(this, ScreenShareService::class.java));result.success(null) }
    "status" -> result.success(org.json.JSONObject().put("capture",ScreenShareService.status).put("task",ScreenShareService.taskStatus).put("active",ScreenShareService.active).toString())
    else -> result.notImplemented()
   }
  }
 }
 override fun onDestroy() {
  UsbLaunchBridge.detachOwner(this)
  ticket?.let { ScreenShareService.revoke(it) };ticket=null
  pending?.error("cancelled","共享授权已中断，请重新开启",null);pending=null
  super.onDestroy()
 }
 @Deprecated("Activity result is required for projection consent")
 override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
  super.onActivityResult(requestCode,resultCode,data)
  if(requestCode!=pendingRequestCode)return
  pendingRequestCode=-1;consentInFlight=false
  val requestedUsb=pendingUsbSession;pendingUsbSession=null
  val reply=pending;pending=null
  val capability=ticket;ticket=null
  if(resultCode!=Activity.RESULT_OK || data==null || capability==null || (requestedUsb!=null && !UsbLaunchBridge.matches(requestedUsb))) {
   capability?.let { ScreenShareService.revoke(it) };reply?.error("cancelled","未同意屏幕共享",null);return
  }
  val intent=Intent(this,ScreenShareService::class.java).putExtra("grant",data).putExtra("ticket",capability).putExtra("usbSession",requestedUsb)
  try {
   if(Build.VERSION.SDK_INT>=26)startForegroundService(intent) else startService(intent)
   reply?.success(null)
  } catch(e: Exception) { ScreenShareService.revoke(capability);reply?.error("start_failed","无法启动屏幕共享",null) }
 }
}
