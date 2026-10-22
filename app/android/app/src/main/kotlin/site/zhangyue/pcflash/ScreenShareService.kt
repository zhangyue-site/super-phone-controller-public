package site.zhangyue.pcflash

import android.app.*
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.graphics.Point
import android.view.WindowManager
import org.json.JSONObject
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.*
import java.io.ByteArrayOutputStream
import java.net.URL
import javax.net.ssl.HttpsURLConnection

class ScreenShareService: Service() {
 companion object {
 @Volatile var active=false
 @Volatile var usbOwnerSerial: String?=null
 @Volatile var status="未共享"
 @Volatile var taskStatus=""
 fun revoke(capability: String) { if(capability.isEmpty())return;Thread {
  var c: HttpsURLConnection?=null
  try { c=URL("$BASE/stop").openConnection() as HttpsURLConnection;c.requestMethod="POST";c.connectTimeout=3000;c.readTimeout=3000;c.doOutput=true;c.setRequestProperty("Authorization","Bearer $capability");c.setFixedLengthStreamingMode(0);c.outputStream.close();c.responseCode } catch(_: Exception) {} finally {c?.disconnect()}
 }.start() }
 private const val BASE="https://erweima.zhangyue.site/phone-controller/app-screen" }
 private fun readBounded(input: java.io.InputStream,limit: Int): ByteArray {
  val out=ByteArrayOutputStream();val buffer=ByteArray(1024)
  while(out.size()<limit){val n=input.read(buffer,0,minOf(buffer.size,limit-out.size()));if(n<0)break;out.write(buffer,0,n)}
  return out.toByteArray()
 }
 private var projection: MediaProjection?=null
 private var display: VirtualDisplay?=null
 private var reader: ImageReader?=null
 private var worker: HandlerThread?=null
 private var handler: Handler?=null
 @Volatile private var running=false
 @Volatile private var connection: HttpsURLConnection?=null
 private var ticket=""
 private var sequence=0
 private var last=0L
 private var until=0L
 private var barrier=""
 private var afterResponse=0L
 private var initialWidth=0
 private var initialHeight=0
 private var initialRotation=0
 private var displayManager: DisplayManager?=null
 private fun geometryChanged() {
  if(!running)return
  running=false;connection?.disconnect();status="屏幕方向或共享范围已改变，任务已取消；请重新共享整个屏幕";taskStatus="";stopSelf()
 }
 private val displayListener=object: DisplayManager.DisplayListener {
  override fun onDisplayAdded(id: Int) {}
  override fun onDisplayRemoved(id: Int) { if(id==android.view.Display.DEFAULT_DISPLAY)geometryChanged() }
  override fun onDisplayChanged(id: Int) {
   if(id!=android.view.Display.DEFAULT_DISPLAY)return
   @Suppress("DEPRECATION") val d=(getSystemService(WINDOW_SERVICE) as WindowManager).defaultDisplay
   val size=Point();d.getRealSize(size)
   if(size.x!=initialWidth || size.y!=initialHeight || d.rotation!=initialRotation)geometryChanged()
  }
 }
 private val poll=object: Runnable {
  override fun run() {
   if(!running)return
   if(SystemClock.elapsedRealtime()>=until){running=false;status="共享凭证已到期，请重新开启";stopSelf();return}
   var c: HttpsURLConnection?=null
   try {
    c=URL("$BASE/status").openConnection() as HttpsURLConnection;connection=c
    c.requestMethod="POST";c.connectTimeout=3000;c.readTimeout=3000;c.doOutput=true
    c.setRequestProperty("Authorization","Bearer $ticket");c.setFixedLengthStreamingMode(0);c.outputStream.close()
    if(c.responseCode==200) {
     val body=c.inputStream.use { readBounded(it,16385) }
     if(body.size>16384)throw IllegalStateException()
     val data=JSONObject(String(body,Charsets.UTF_8))
     if(running)taskStatus=data.toString()
    } else if(c.responseCode==401 || c.responseCode==403) {running=false;status="共享授权失效，请重新开启";stopSelf()}
   } catch(_: Exception) {if(running)taskStatus=""} finally {c?.disconnect();connection=null}
   if(running)handler?.postDelayed(this,2000)
  }
 }
 override fun onBind(intent: Intent?)=null
 override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
  if(intent?.action=="STOP"){status="已停止共享";stopSelf();return START_NOT_STICKY}
  if(running || active){intent?.getStringExtra("ticket")?.let { revoke(it) };return START_NOT_STICKY}
  val value=intent?.getStringExtra("ticket")
  @Suppress("DEPRECATION") val grant=intent?.getParcelableExtra<Intent>("grant")
  if(value==null || grant==null){stopSelf();return START_NOT_STICKY}
  val usbSession=intent?.getStringExtra("usbSession")
  if(usbSession!=null && !UsbLaunchBridge.matches(usbSession)){revoke(value);status="控制板已拔出，请重新共享";stopSelf();return START_NOT_STICKY}
  ticket=value;usbOwnerSerial=UsbLaunchBridge.serialFor(usbSession);active=true
  val nm=getSystemService(NOTIFICATION_SERVICE) as NotificationManager
  if(Build.VERSION.SDK_INT>=26)nm.createNotificationChannel(NotificationChannel("screen", "AI屏幕共享", NotificationManager.IMPORTANCE_LOW))
  val stop=PendingIntent.getService(this,0,Intent(this,ScreenShareService::class.java).setAction("STOP"),PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
  val builder=if(Build.VERSION.SDK_INT>=26)Notification.Builder(this,"screen") else Notification.Builder(this)
  val notification=builder.setSmallIcon(android.R.drawable.ic_menu_view).setContentTitle("正在向你的AI共享屏幕").setContentText("手机操作由控制板HID完成；点此停止共享").setOngoing(true).setContentIntent(stop).addAction(android.R.drawable.ic_menu_close_clear_cancel,"停止",stop).build()
  try {
  if(Build.VERSION.SDK_INT>=29)startForeground(71,notification,ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION) else startForeground(71,notification)
   worker=HandlerThread("screen-capture").also{it.start()};handler=Handler(worker!!.looper)
   projection=(getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager).getMediaProjection(Activity.RESULT_OK,grant)
   projection!!.registerCallback(object: MediaProjection.Callback(){override fun onStop(){if(running)status="系统已停止共享";running=false;stopSelf()}
    override fun onCapturedContentResize(width: Int,height: Int){if(width!=initialWidth || height!=initialHeight)geometryChanged()}},Handler(Looper.getMainLooper()))
   val metrics=resources.displayMetrics
   @Suppress("DEPRECATION") val physical=(getSystemService(WINDOW_SERVICE) as WindowManager).defaultDisplay
   val size=Point();physical.getRealSize(size)
   val width=size.x;val height=size.y
   initialWidth=width;initialHeight=height;initialRotation=physical.rotation
   displayManager=getSystemService(DISPLAY_SERVICE) as DisplayManager
   displayManager!!.registerDisplayListener(displayListener,handler)
   reader=ImageReader.newInstance(width,height,PixelFormat.RGBA_8888,2)
   until=SystemClock.elapsedRealtime()+270000L;running=true;taskStatus="";handler!!.post(poll);status="共享中，等待语音任务"
   reader!!.setOnImageAvailableListener({ source ->
    val image=source.acquireLatestImage() ?: return@setOnImageAvailableListener
    var bitmap: Bitmap?=null
    var cropped: Bitmap?=null
    var scaled: Bitmap?=null
    try {
     val now=SystemClock.elapsedRealtime()
     if(!running || image.timestamp<=afterResponse)return@setOnImageAvailableListener
     @Suppress("DEPRECATION") val currentDisplay=(getSystemService(WINDOW_SERVICE) as WindowManager).defaultDisplay
     val currentSize=Point();currentDisplay.getRealSize(currentSize)
     if(currentDisplay.rotation!=initialRotation || currentSize.x!=initialWidth || currentSize.y!=initialHeight){geometryChanged();return@setOnImageAvailableListener}
     if(image.width!=initialWidth || image.height!=initialHeight){geometryChanged();return@setOnImageAvailableListener}
     if(now>=until){status="共享凭证已到期，请重新开启";stopSelf();return@setOnImageAvailableListener}
     if(now-last<800)return@setOnImageAvailableListener
     last=now
     val plane=image.planes[0];val padding=plane.rowStride-plane.pixelStride*image.width
     bitmap=Bitmap.createBitmap(image.width+padding/plane.pixelStride,image.height,Bitmap.Config.ARGB_8888)
     bitmap!!.copyPixelsFromBuffer(plane.buffer)
     cropped=Bitmap.createBitmap(bitmap!!,0,0,image.width,image.height)
     // Resize the entire display, never a target-app crop. Coordinates remain normalized.
     val factor=minOf(1.0,720.0/image.width,1280.0/image.height)
     scaled=if(factor<1.0)Bitmap.createScaledBitmap(cropped!!,(image.width*factor).toInt().coerceAtLeast(1),(image.height*factor).toInt().coerceAtLeast(1),true) else cropped
     val bytes=ByteArrayOutputStream().use { out -> scaled!!.compress(Bitmap.CompressFormat.JPEG,70,out);out.toByteArray() }
     if(bytes.size>524288){running=false;status="画面过大，任务已停止；请降低屏幕分辨率后重新共享";stopSelf();return@setOnImageAvailableListener}
     val conn=URL("$BASE/frame").openConnection() as HttpsURLConnection
     connection=conn;conn.requestMethod="POST";conn.connectTimeout=5000;conn.readTimeout=5000;conn.doOutput=true
     conn.setRequestProperty("X-Screen-Native-Width",initialWidth.toString());conn.setRequestProperty("X-Screen-Native-Height",initialHeight.toString());conn.setRequestProperty("X-Screen-Barrier",barrier);conn.setRequestProperty("Authorization","Bearer $ticket");conn.setRequestProperty("Content-Type","image/jpeg");conn.setRequestProperty("X-Screen-Sequence",(++sequence).toString());conn.setFixedLengthStreamingMode(bytes.size)
     conn.outputStream.use{it.write(bytes)}
     val code=conn.responseCode
     if(code==200 || code==202) {
      val body=conn.inputStream.use { readBounded(it,4097) }
      if(body.size>4096)throw IllegalStateException()
      val response=JSONObject(String(body,Charsets.UTF_8))
      val next=response.getString("barrier")
      if(!Regex("[0-9a-f]{32}").matches(next))throw IllegalStateException()
      barrier=next;afterResponse=System.nanoTime()
      if(running)status=if(code==200)"画面传输：已上传" else "画面传输：共享中"
     } else {running=false;status="共享授权失效，请重新开启";stopSelf()}
     conn.disconnect();connection=null
    } catch(e: Exception) {if(running)status="画面上传失败，正在重试"}
    finally {if(scaled!==cropped)scaled?.recycle();if(cropped!==bitmap)cropped?.recycle();bitmap?.recycle();image.close();connection?.disconnect();connection=null}
   },handler)
   display=projection!!.createVirtualDisplay("AI phone screen",width,height,metrics.densityDpi,DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,reader!!.surface,null,handler)
  } catch(e: Exception) {status="屏幕共享启动失败，请重新授权";stopSelf()}
  return START_NOT_STICKY
 }
 override fun onDestroy() {
  active=false;usbOwnerSerial=null
  running=false;connection?.disconnect()
  display?.release();display=null;reader?.close();reader=null
  val old=projection;projection=null;old?.stop();worker?.quitSafely();worker=null
  handler?.removeCallbacksAndMessages(null);displayManager?.unregisterDisplayListener(displayListener)
  taskStatus=""
  val capability=ticket;ticket="";revoke(capability)
  stopForeground(STOP_FOREGROUND_REMOVE);super.onDestroy()
 }
}
