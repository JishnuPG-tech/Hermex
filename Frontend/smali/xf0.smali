.class public final Lxf0;
.super Lzf0;
.source "SourceFile"


# static fields
.field public static final g:Lxf0;


# direct methods
.method static constructor <clinit>()V
    .locals 6

    new-instance v0, Lxf0;

    sget-object v2, Lcom/anthropic/hermes/types/environment/AppEnvironment;->PRODUCTION:Lcom/anthropic/hermes/types/environment/AppEnvironment;

    const-string v1, "https://jishnupg-hermes.hf.space/hermes/"

    const-string v3, "https://jishnupg-hermes.hf.space"

    filled-new-array {v1, v3}, [Ljava/lang/String;

    move-result-object v1

    invoke-static {v1}, Lnr0;->A0([Ljava/lang/Object;)Ljava/util/Set;

    move-result-object v4

    const/16 v5, 0x8

    const-string v1, "https://jishnupg-hermes.hf.space/hermes/"

    const/4 v3, 0x0

    invoke-direct/range {v0 .. v5}, Lzf0;-><init>(Ljava/lang/String;Lcom/anthropic/hermes/types/environment/AppEnvironment;ZLjava/util/Set;I)V

    sput-object v0, Lxf0;->g:Lxf0;

    return-void
.end method


# virtual methods
.method public final equals(Ljava/lang/Object;)Z
    .locals 1

    const/4 v0, 0x1

    if-ne p0, p1, :cond_0

    return v0

    :cond_0
    instance-of p0, p1, Lxf0;

    if-nez p0, :cond_1

    const/4 p0, 0x0

    return p0

    :cond_1
    return v0
.end method

.method public final hashCode()I
    .locals 0

    const p0, -0xceab789

    return p0
.end method

.method public final toString()Ljava/lang/String;
    .locals 0

    const-string p0, "Production"

    return-object p0
.end method
