import kn.uni.sen.tartar.smtcall.Z3Call;

public class RunTarTarQE {
    public static void main(String[] args) {
        if (args.length < 1) {
            System.out.println("usage: RunTarTarQE <smt2_file> [timeout_ms]");
            System.exit(2);
        }
        String smt2File = args[0];
        int timeout = 0;
        if (args.length >= 2) {
            timeout = Integer.parseInt(args[1]);
        }
        Z3Call.timeout = timeout;
        Z3Call z3 = new Z3Call();
        long start = System.currentTimeMillis();
        boolean ok = z3.runEliminationFile(smt2File);
        long elapsed = System.currentTimeMillis() - start;
        System.out.println("qe_ok=" + ok);
        System.out.println("elapsed_ms=" + elapsed);
        String model = z3.getEliminatedModel();
        if (model == null) {
            System.out.println("eliminated_model=null");
        } else {
            System.out.println("eliminated_model_len=" + model.length());
            boolean hasForall = model.contains("(forall ");
            boolean hasExists = model.contains("(exists ");
            System.out.println("contains_quantifier=" + (hasForall || hasExists));
        }
    }
}
