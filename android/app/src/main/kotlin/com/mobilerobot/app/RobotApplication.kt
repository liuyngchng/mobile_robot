package com.mobilerobot.app

import android.app.Application

class RobotApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        System.loadLibrary("sherpa_onnx_jni")
    }
}
