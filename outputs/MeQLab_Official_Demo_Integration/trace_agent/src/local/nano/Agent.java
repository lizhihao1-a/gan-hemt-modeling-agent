package local.nano;

import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.security.ProtectionDomain;
import java.io.File;
import java.util.jar.JarFile;
import jdk.internal.org.objectweb.asm.*;

/** Diagnostic instrumentation: record call boundaries and returned values only. */
public final class Agent {
    public static void premain(String target, Instrumentation inst) throws Exception {
        System.setProperty("local.nano.trace", target);
        File jar = new File(Agent.class.getProtectionDomain().getCodeSource().getLocation().toURI());
        inst.appendToBootstrapClassLoaderSearch(new JarFile(jar));
        inst.addTransformer(new Transformer());
    }

    public static final class Transformer implements ClassFileTransformer {
        public byte[] transform(ClassLoader loader, String cls, Class<?> prior,
                                ProtectionDomain domain, byte[] bytes) {
            if (cls == null || !(
                cls.equals("com/platformda/simulate/pei/SocketPei") ||
                cls.equals("com/platformda/simulate/pei/GrpcPei") ||
                cls.equals("com/platformda/simulate/pei/PeiManager") ||
                cls.equals("com/platformda/simulate/pei/BasePeiSimulator") ||
                cls.equals("com/platformda/simulate/pei/PeiDoubleSweepSimulator") ||
                cls.equals("com/platformda/simulate/pei/PeiDoubleSweepByDeviceSimulator") ||
                cls.equals("com/platformda/simulate/pei/PeiDistributedExecutor") ||
                cls.equals("com/platformda/simulate/DistributedJobExecutor") ||
                cls.equals("com/platformda/extraction/simulate/SimEntryManager"))) return null;
            try {
                ClassReader cr = new ClassReader(bytes);
                ClassWriter cw = new ClassWriter(cr, ClassWriter.COMPUTE_MAXS);
                cr.accept(new ClassVisitor(Opcodes.ASM8, cw) {
                    public MethodVisitor visitMethod(int access, String name, String desc,
                                                     String signature, String[] exceptions) {
                        MethodVisitor mv = super.visitMethod(access, name, desc, signature, exceptions);
                        if (cls.equals("com/platformda/simulate/pei/PeiManager") && name.equals("buildStartServerCmd")) {
                            return new MethodVisitor(Opcodes.ASM8, mv) {
                                public void visitCode() {
                                    super.visitCode();
                                    super.visitLdcInsn("local.nano.wrapper");
                                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "java/lang/System", "getProperty", "(Ljava/lang/String;)Ljava/lang/String;", false);
                                    super.visitVarInsn(Opcodes.ASTORE, 0);
                                    super.visitInsn(Opcodes.ICONST_1);
                                    super.visitVarInsn(Opcodes.ISTORE, 2);
                                }
                            };
                        }
                        if (cls.equals("com/platformda/simulate/pei/PeiManager") && name.equals("fixEnvironmentVariables")) {
                            return new MethodVisitor(Opcodes.ASM8, mv) {
                                public void visitInsn(int opcode) {
                                    if (opcode == Opcodes.RETURN) {
                                        super.visitVarInsn(Opcodes.ALOAD, 0);
                                        super.visitMethodInsn(Opcodes.INVOKESTATIC, "local/nano/Trace", "environment", "(Ljava/lang/ProcessBuilder;)V", false);
                                    }
                                    super.visitInsn(opcode);
                                }
                            };
                        }
                        if ((access & (Opcodes.ACC_NATIVE | Opcodes.ACC_ABSTRACT)) != 0 ||
                            name.startsWith("<") || name.startsWith("lambda$")) return mv;
                        if (!(name.startsWith("pei_") || name.equals("newSim") ||
                              name.equals("doBatch") || name.equals("doSimulation") ||
                              name.equals("executeJob") || name.equals("execute") ||
                              name.equals("doSimulate"))) return mv;
                        String key = cls.substring(cls.lastIndexOf('/') + 1) + "." + name + desc;
                        return new MethodVisitor(Opcodes.ASM8, mv) {
                            public void visitCode() {
                                super.visitCode();
                                super.visitLdcInsn(key);
                                super.visitMethodInsn(Opcodes.INVOKESTATIC, "local/nano/Trace", "entry", "(Ljava/lang/String;)V", false);
                                if (cls.endsWith("/SocketPei") && name.equals("pei_newSim") && desc.equals("(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)I")) {
                                    super.visitVarInsn(Opcodes.ALOAD, 2);
                                    super.visitVarInsn(Opcodes.ALOAD, 3);
                                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "local/nano/Trace", "tokenShape", "(Ljava/lang/String;Ljava/lang/String;)V", false);
                                }
                            }
                            public void visitInsn(int opcode) {
                                if (opcode == Opcodes.IRETURN) {
                                    super.visitInsn(Opcodes.DUP);
                                    super.visitLdcInsn(key);
                                    super.visitInsn(Opcodes.SWAP);
                                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "local/nano/Trace", "intResult", "(Ljava/lang/String;I)V", false);
                                } else if (opcode == Opcodes.DRETURN && name.equals("pei_getValue")) {
                                    super.visitInsn(Opcodes.DUP2);
                                    super.visitLdcInsn(key);
                                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "local/nano/Trace", "doubleResult", "(DLjava/lang/String;)V", false);
                                } else if (opcode == Opcodes.ARETURN && name.equals("pei_getResult")) {
                                    super.visitInsn(Opcodes.DUP);
                                    super.visitLdcInsn(key);
                                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "local/nano/Trace", "objectResult", "(Ljava/lang/Object;Ljava/lang/String;)V", false);
                                }
                                super.visitInsn(opcode);
                            }
                        };
                    }
                }, 0);
                return cw.toByteArray();
            } catch (Throwable e) {
                Trace.message("Transformer error for " + cls + ": " + e);
                return null;
            }
        }
    }
}
