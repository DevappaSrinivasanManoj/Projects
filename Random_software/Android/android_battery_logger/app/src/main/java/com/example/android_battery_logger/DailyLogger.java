
package com.example.android_battery_logger;

import android.content.Context;
import android.os.BatteryManager;
import android.os.Environment;

import androidx.annotation.NonNull;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

public class DailyLogger extends Worker {

    public DailyLogger(@NonNull Context context, @NonNull WorkerParameters workerParams) {
        super(context, workerParams);
    }

    @NonNull
    @Override
    public Result doWork() {
        logBatteryPercentage();
        return Result.success();
    }

    private void logBatteryPercentage() {
        Context context = getApplicationContext();
        BatteryManager bm = (BatteryManager) context.getSystemService(Context.BATTERY_SERVICE);
        int batteryLevel = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY);
        String timeStamp = new SimpleDateFormat("dd MMM yyyy HH:mm", Locale.getDefault()).format(new Date());
        String logMessage = "Battery percentage at " + timeStamp + " : " + batteryLevel + "%\n";
        writeLog(logMessage);
    }

    private void writeLog(String logMessage) {
        try {
            File logFile = new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOCUMENTS), "BatteryLogs/battery_log.txt");
            if (!logFile.getParentFile().exists()) {
                logFile.getParentFile().mkdirs();
            }
            FileWriter writer = new FileWriter(logFile, true);
            writer.append(logMessage);
            writer.flush();
            writer.close();
        } catch (IOException e) {
            e.printStackTrace();
        }
    }
}
