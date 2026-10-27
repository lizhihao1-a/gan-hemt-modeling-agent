package local.nano;

import java.io.*;
import java.time.OffsetDateTime;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

/** Never records input arguments, license material, or changes returned values. */
public final class Trace {
    private static final ConcurrentHashMap<String, AtomicInteger> counts = new ConcurrentHashMap<>();
    private static PrintWriter writer;
    public static synchronized void message(String text) {
        try {
            if (writer == null) writer = new PrintWriter(new FileWriter(System.getProperty("local.nano.trace"), true), true);
            writer.println(OffsetDateTime.now() + " " + text);
        } catch (Exception ignored) { }
    }
    private static boolean take(String key) { return counts.computeIfAbsent(key, k -> new AtomicInteger()).incrementAndGet() <= 30; }
    public static void entry(String key) { if (take("entry:"+key)) message("ENTER " + key); }
    public static void intResult(String key, int value) { if (take("int:"+key)) message("RETURN " + key + " = " + value); }
    public static void doubleResult(double value, String key) { if (take("double:"+key)) message("RETURN " + key + " = " + value); }
    public static void objectResult(Object value, String key) {
        if (take("object:"+key)) {
            String text = String.valueOf(value).replace('\n',' ').replace('\r',' ');
            message("RETURN " + key + " = " + text.substring(0, Math.min(text.length(), 240)));
        }
    }
    public static void tokenShape(String a, String b) {
        message("TOKEN_METADATA lt_present="+(a!=null)+"; lt_length="+(a==null?0:a.length())+"; vt_present="+(b!=null)+"; vt_length="+(b==null?0:b.length()));
    }
    public static void environment(ProcessBuilder p) {
        for (String k : p.environment().keySet()) {
            if (k.equalsIgnoreCase("path") || k.equals("PROSIM_root")) message("ENGINE_ENV " + k + "=" + p.environment().get(k));
        }
    }
}
